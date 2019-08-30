/* Python3 extension to interact with CRASH
 * WARNING: it will not work with Python2!
 *
 *
 * # --------------------------------------------------------------------
 * # (C) Copyright 2006-2019 Hewlett Packard Enterprise Development LP
 * #
 * # Author: Alex Sidorenko <asid@hpe.com>
 * #
 * # --------------------------------------------------------------------
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 */

#include <Python.h>
#include <compile.h>        /* for PyCodeObject typedef on older releases */
#include <eval.h>           /* for PyEval_EvalCode om older released */

#include <unistd.h>
#include <getopt.h>
#include <limits.h>
#include <stdlib.h>
#include <libgen.h>
#include <sys/times.h>


#include "defs.h"    /* From the crash source top-level directory */


int debug = 0;

/* This is C-module version */
static char crashmod_version_s[] = "@(#)pycrash 3.1.0";
const char * crashmod_version = crashmod_version_s + 12;

extern const char *build_crash_version;

#include "pykdump.h"


static char *ext_filename = NULL;
#define BUFLEN 1024

const char *py_vmcore_realpath = NULL;

/* Initialize the crashmodule stuff */
PyMODINIT_FUNC PyInit_crash(void);


// In "defs.h", 'FILE *fp' is a file object used by crash.
// If we want mix our output with crash's output, we need to connect stdout
// to it.
// But there is a potential problem - Python now has its own layer of buffering

// connect sys.stdout to fp

void connect2fp(void) {
    PyObject *crashfp;
    PyObject* sys = PyImport_ImportModule("sys");     // New reference

    crashfp = PyFile_FromFd(fileno(fp), "<crash fp>", "w",
                            -1, NULL, NULL, NULL, 0);

    PyObject_SetAttrString(sys, "stdout", crashfp);
    PyObject_SetAttrString(sys, "stderr", crashfp);
    Py_DECREF(sys);
}

void epython_execute_prog(int argc, char *argv[], int quiet);

static int run_fromzip(const char *progname, const char* zipfile);


/* ============ Dealing with SIGINT =====================
 *
 *   Both Python and crash/gdb have SIGINT handlers and to avoid
 *   conflict we need to use a proper handler depending on context:
 *   - when executing Python code not using this module, use Python handler
 *   - when executing commands such as exec_crash_command, use crash.gdb handler
 *
 */

// Default SIGINT handlers: crash/GDB and Python. We save them during
// extension loading, in its init subroutine
static struct sigaction crashgdb_sa, py_sa;

// For debugging
void checksignals(void) {
    struct sigaction sa;
    sigaction(SIGINT, NULL, &sa);
    fprintf(stderr, "crash=%p, python=%p, current=%p\n",
            crashgdb_sa.sa_handler, py_sa.sa_handler, sa.sa_handler);
}

// Use Python SIGINT handler
void use_python_sigint(void) {
    sigaction (SIGINT, &py_sa, NULL);
}

// Use crash SIGINT handler
void use_crash_sigint(void) {
    sigaction (SIGINT, &crashgdb_sa, NULL);
}



// The next pair of functions makes it possible to run some Python subroutines
// just before we start executing 'epython ...' and before we return
// to 'crash' prompt
// The names of these Python subroutines are obtained from
// sys.enterepython and sys.exitepython

// Entering
static void
call_sys_enterepython(void)
{
    PyObject *enterfunc = PySys_GetObject("enterepython");

    if (enterfunc) {
        PyObject *res;
        Py_INCREF(enterfunc);
        //PySys_SetObject("enterepython", (PyObject *)NULL);
        res = PyEval_CallObject(enterfunc, (PyObject *)NULL);
        if (res == NULL) {
            if (!PyErr_ExceptionMatches(PyExc_SystemExit)) {
                PySys_WriteStderr("Error in sys.enterepython:\n");
            }
            PyErr_Print();
        }
        Py_DECREF(enterfunc);
    }
    PyErr_Clear();
}

// Exiting
static void
call_sys_exitepython(void)
{
    PyObject *exitfunc = PySys_GetObject("exitepython");

    if (exitfunc) {
        PyObject *res;
        Py_INCREF(exitfunc);
        //PySys_SetObject("exitepython", (PyObject *)NULL);
        //connect2fp();
        res = PyEval_CallObject(exitfunc, (PyObject *)NULL);
        if (res == NULL) {
            if (!PyErr_ExceptionMatches(PyExc_SystemExit)) {
                PySys_WriteStderr("Error in sys.exitepython:\n");
            }
            PyErr_Print();
        }
        Py_DECREF(exitfunc);
    }
    PyErr_Clear();
}

void cmd_epython(void);     /* Declare the commands and their help data. */
char *help_epython[];

static struct command_table_entry command_table[] = {
    {"epython", cmd_epython, help_epython, 0}, /* One or more commands, */
    { NULL,}			/* terminated by NULL, */
};

struct extension_table *epython_curext;

// We can specify extra path to search for modules and progs
// by setting PYKDUMPPATH environment variable.
// The order of search is like that:
// 1. Current directory
// 2. PYKDUMPPATH (if set, syntax the same as for normal shell PATH)
// 3. ZIP-archive embedded in our pykdump.so
const char *extrapath;


/* There is a problem when unloading the extension built with Python
 *   shared library. In this case we load other .so files as needed.
 *   As a result, the reference count of or .so does not go to zero and
 *   when you load again, _init is not called. This is true even for
 *   __attribute__ mechanism. But everything's OK for ZIPped version
 */

char stdpath[BUFLEN];
wchar_t wstdpath[BUFLEN];

/* Old-style constructrs/destructors for dlopen. */
void _init(void)  {
    //void __attribute__((constructor)) n_init(void) {
    //PyObject *syspath;

    //PyObject *s;

    struct command_table_entry *ct_copy;
    /*
     *    WARNING:
     *    dlopen() manpage says that _init() is not very reliable and can be called
     *    twice in some cases.
     */
    if (getenv("PYKDUMPDEBUG"))
        debug = atoi(getenv("PYKDUMPDEBUG"));
    if (debug)
        printf("Running epython_init\n");

    // If crash is in 'minimal' mode, we just bail out as we depend on full
    // crash functionality
    if (pc->flags & MINIMAL_MODE)
        return;

    /* Before doing anything else, check whether the versions of crash
     *    used for build and the currently running version are compatible:
     *    build_crash_version vs build_version
     */

    if (build_crash_version[0] != build_version[0]) {
        fprintf(stderr, "\nYou need to use mpykdump.so matching the major"
        " crash version\n");
        fprintf(stderr, "crash used for build: %s, currently running: %s\n",
                build_crash_version, build_version);
        fprintf(stderr, "Cannot continue, exiting\n\n");
        exit(1);
    }


    ext_filename = malloc(strlen(pc->curext->filename)+1);
    strcpy(ext_filename,  pc->curext->filename);
    if (debug)
        printf("extname=%s\n", ext_filename);

    // Store our extension table for registering subcommands
    epython_curext = pc->curext;

    if (!Py_IsInitialized()) {
        Py_NoSiteFlag = 1;
        Py_FrozenFlag = 1;
        Py_IgnoreEnvironmentFlag = 1;
        Py_SetPythonHome(EMPTYS);
        if (debug)
            fprintf(fp, "     *** Initializing Embedded Python %s ***\n",
                    crashmod_version);

        extrapath = getenv("PYKDUMPPATH");
        // To be able debug sources, we need real FS to be searched
        // before ZIP. So if PYKDUMPPATH is set, we insert it _before_ our
        // ZIP-archive
        //strcpy(stdpath, ".:");
        strcpy(stdpath, "");
        if (extrapath) {
            strncat(stdpath, extrapath, BUFLEN-1);
            strncat(stdpath, ":", BUFLEN-1);
        }
        strncat(stdpath, ext_filename, BUFLEN-1);
        strncat(stdpath, ":", BUFLEN-1);
        strncat(stdpath, ext_filename, BUFLEN-1);
        strncat(stdpath, "/", BUFLEN-1);
        strncat(stdpath, PYSTDLIBDIR, BUFLEN-1);
        strncat(stdpath, ":", BUFLEN);
        strncat(stdpath, ext_filename, BUFLEN-1);
        strncat(stdpath, "/", BUFLEN-1);
        strncat(stdpath, PYEXTRADIR, BUFLEN-1);
        mbstowcs(wstdpath, stdpath, BUFLEN-1);

        PyImport_AppendInittab("crash", PyInit_crash);
        Py_SetPath(wstdpath);

        // Get crash/gdb SIGINT handler and store it.
        sigaction(SIGINT, NULL, &crashgdb_sa);
        // Set SIG_DFL - we need this to get Python handler initialized
        py_sa.sa_handler = SIG_DFL;
        sigemptyset (&py_sa.sa_mask);
        py_sa.sa_flags = 0;
        sigaction(SIGINT, &py_sa, NULL);
        Py_Initialize();
        // Get Python SIGINT handler and store it
        sigaction(SIGINT, NULL, &py_sa);
        //checksignals();
        PyEval_InitThreads();
    } else {
        if (debug)
            printf("Trying to Py_Initialize() twice\n");
    }

    /* Make a copy of the initial command table on heap, so we'll be able to
     *     modify it if needed
     */

    ct_copy = (struct command_table_entry *) malloc(sizeof(command_table));
    if (!ct_copy) {
        printf("Cannot allocate ct_copy\n");
        exit(1);
    }
    memcpy(ct_copy, command_table, sizeof(command_table));
    register_extension(ct_copy);

    // Set scroll if it has not been done yet

    if (pc->flags & SCROLL) {
        printf("Setting scroll off while initializing PyKdump\n");
        pc->flags &= ~SCROLL;
    }


    if (debug) {
        printf("Epython extension registered\n");
        PyRun_SimpleString("import sys; print (sys.path)");
    }

    // Get the realpath of vmcore
    if (pc->dumpfile)
        py_vmcore_realpath = realpath(pc->dumpfile, NULL);
    else if (pc->live_memsrc)
        py_vmcore_realpath = realpath(pc->live_memsrc, NULL);


    if (debug)
        fprintf(fp, "vmcore=<%s>\n", py_vmcore_realpath);
    // Run the initialization Python script if it is available
    {
        char *argv[]= {"_init", "PyKdumpInit", NULL};
        epython_execute_prog(2, argv, 1);
    }

    return;
}

// Don't call this when run in a separate thread - it saves time
// and avoid conflicts with threading

int _unload_epython = 1;
void _fini(void) {
    //void __attribute__((destructor)) n_fini(void) {
    struct command_table_entry *ce;

    // We do nothing in minimal mode
    if (pc->flags & MINIMAL_MODE)
        return;

    if (! _unload_epython)
        return;

    if (debug)
        fprintf(fp, "Unloading epython\n");
    free(ext_filename);
    ext_filename = NULL;
    Py_Finalize();

    // Free name and help pointers for added entries
    for (ce = epython_curext->command_table, ce++; ce->name; ce++) {
        if (debug)
            fprintf(fp, "freeing ce->name and ce->help_data for %s\n", ce->name);
        free(ce->name);
        if (ce->help_data)
            free(ce->help_data);
    }

    free(epython_curext->command_table);
    if (py_vmcore_realpath)
        free((void *)py_vmcore_realpath);
}

// Emulate PyRun_SimpleFile but with a special sys.exit() handling
int PyKdump_Run_File(FILE *_fp, const char *filename) {
    int closeit = 0;
    PyCompilerFlags *flags = NULL;
    
    PyObject *m, *d, *v;
    int set_file_name = 0, ret = -1;

    m = PyImport_AddModule("__main__");
    if (m == NULL)
        return -1;
    Py_INCREF(m);
    d = PyModule_GetDict(m);
    if (PyDict_GetItemString(d, "__file__") == NULL) {
        PyObject *f;
        f = PyUnicode_DecodeFSDefault(filename);
        if (f == NULL)
            goto done;
        if (PyDict_SetItemString(d, "__file__", f) < 0) {
            Py_DECREF(f);
            goto done;
        }
        if (PyDict_SetItemString(d, "__cached__", Py_None) < 0) {
            Py_DECREF(f);
            goto done;
        }
        set_file_name = 1;
        Py_DECREF(f);
    }

    v = PyRun_FileExFlags(_fp, filename, Py_file_input, d, d,
                              closeit, flags);
    if (v == NULL) {
        PyObject *exc = PyErr_Occurred();
        Py_CLEAR(m);
        
        if (PyErr_GivenExceptionMatches(exc, PyExc_SystemExit)) {
            // If this was sys.exit(n), do not terminate the program.
            PyObject *p_type, *p_value, *p_traceback;
            PyErr_Fetch(&p_type, &p_value, &p_traceback);
            long i = PyLong_AsLong(p_value);
            // for sys.exit() we have None-> -1
            if (i > 0) {
                fprintf(fp, " -- sys.exit(%ld) --\n", i);
                fflush(fp);
            }
        } else
            PyErr_Print();
        PyErr_Clear();
        goto done;
    }
    Py_DECREF(v);
    ret = 0;
  done:
    if (set_file_name && PyDict_DelItemString(d, "__file__"))
        PyErr_Clear();

    Py_XDECREF(m);
    return ret;
}

/*
 *  Try to run the program from internal ZIP (should be in progs/).
 */

static int
run_fromzip(const char *progname, const char *zipfilename) {
    PyObject  *m, *importer;
    evalPyObject *code;
    PyObject *d, *v;
    //PyObject *ZipImportError;
    if (debug)
        printf("run_fromzip(%s, %s)\n", progname, zipfilename);
    m = PyImport_ImportModule("zipimport");
    if (!m) {
        printf("Cannot import <zipimport> module\n");
        return 0;
    }
    importer = PyObject_CallMethod(m, "zipimporter", "s", zipfilename);
    if (!importer) {
        if (debug)
		printf("Failed to import zipfile %s\n", zipfilename);
        return 0;
    }
    Py_DECREF(m);

    code = (evalPyObject *) PyObject_CallMethod(importer, "get_code", "s",
                                                progname);
    Py_DECREF(importer);
    if (!code) {
        if (debug)
            printf("Cannot getcode for <%s>\n", progname);
        PyErr_Clear();
        return 0;
    }

    m = PyImport_AddModule("__main__");
    if (m == NULL) {
        PyErr_Print();
        return 0;
    }

    d = PyModule_GetDict(m);
    v =  PyString_FromString(progname);
    PyDict_SetItemString(d, "__file__", v);
    Py_DECREF(v);

    /* Execute code in __main__ context */
    if (debug)
        printf("Executing code from ZIP\n\n");
    v = PyEval_EvalCode(code, d, d);

    Py_DECREF(code);

    if (v == NULL) {
        // Even though we have been able to run the program, it has ended
        // raising an exception
        if (PyErr_ExceptionMatches(PyExc_IOError)) {
            // We don't want to print error messages for Broken pipe
            // as they occur when we use a scroller and press 'q'
            // before reaching the end of output
            if (errno != EPIPE)
                PyErr_Print();
            else
                PyErr_Clear();
        } else if (PyErr_ExceptionMatches(PyExc_SystemExit)) {
            // If this was sys.exit(n), do not terminate the program.
            PyObject *p_type, *p_value, *p_traceback;
            PyErr_Fetch(&p_type, &p_value, &p_traceback);
            long i = PyLong_AsLong(p_value);
            // for sys.exit() we have None-> -1
            if (i > 0) {
                fprintf(fp, " -- sys.exit(%ld) --\n", i);
                fflush(fp);
            }
        } else
            PyErr_Print();
        PyErr_Clear();
        return 1;
    }
    Py_DECREF(v);
    return 1;

}

/*
 *  Arguments are passed to the command functions in the global args[argcnt]
 *  array.  See getopt(3) for info on dash arguments.  Check out defs.h and
 *  other crash commands for usage of the myriad of utility routines available
 *  to accomplish what your task.
 */



/* Search for our Python program:
 *	    1. Check whether we have it in the current directory
 *	    2. Check in the PATH
 *	    3. If filename does not have '.py' suffix, repeat (1-2)
 *	       after appending it to the specified name
 */

const char *find_pyprog(const char *prog) {
    //char progpy[BUFSIZE];
    char buf2[BUFSIZE];
    static char buf1[BUFSIZE];
    char *tok;

    //If prognames start from '/', no need to search
    if (prog[0] == '/')
        return prog;

    if (extrapath) {
        strcpy(buf2, ".:");
        strncat(buf2, extrapath, BUFSIZE-1);
    } else
        strcpy(buf2, ".");

    tok = strtok(buf2, ":");
    while (tok) {
        snprintf(buf1, BUFSIZE, "%s/%s", tok, prog);
        if (debug > 2)
            printf("Checking %s\n", buf1);
        if (file_exists(buf1, NULL)) {
            if (debug > 1)
                printf("Found: %s\n",  buf1);
            return buf1;
        }
        snprintf(buf1, BUFSIZE, "%s/%s.py", tok, prog);
        if (debug > 2)
            printf("Checking %s\n", buf1);
        if (file_exists(buf1, NULL)) {
            if (debug > 2)
                printf("Found: %s\n",  buf1);
            return buf1;
        }
        tok = strtok(NULL, ":");
    }
    return NULL;
}

/*
 *  This subroutine executes a Python program in crash environment.
 *  We pass to it argc and argv.
 *  If 'quiet' is 1, we do not report errors and do not print stats.
 *  This is used for one-time initialiation script
 *
 *  We use the same convention as for exec() system calls: argv[0] is not
 *  the name of the program but rather something used for information purposes
 *  and useful for debugging
 */

static void ep_usage(void) {
    fprintf(fp, "Usage: \n"
    "  epython [epythonoptions] [progname [--ehelp] [progoptions] [progargs]]\n"
    "    epythonoptions:\n"
    "    ---------------\n"
    "      [-h|--help] \n"
    "      [-v|--version]  - report versions\n"
    "      [-d|--debug n]  - set debugging level \n"
    "      [-p|--path]     - show Python version and syspath\n"
    "      [--ehelp]       - show extra options, common for all programs\n"
    "\n");
}



    


void
epython_execute_prog(int argc, char *argv[], int quiet) {
    FILE *scriptfp = NULL;
    //static long TICKSPS;
    //const char *pypath;
    const char *prog;
    char buffer[BUFLEN];
    char **nargv;
    wchar_t **argv_copy = NULL;
    wchar_t **argv_copy2 = NULL;
    int i;

    // Options/args processing.
    // The general approach we use is like that:
    // epython [eopt1] [eopt2] ... progname [popt1] ...
    // That is - all options specified before the first real arg (progname)
    // are internal for epython


    static struct option long_options[] = {
        {"help",     no_argument,       0, 'h' },
        {"version",  no_argument,       0, 'v' },
        {"debug",    required_argument, 0, 'd' },
        {"path",     no_argument,       0, 'p' },
        {0,          0,             0, 0 }
    };

    int need_prog = 1;		/* Usually we need a prog argument */
    int c;
    int option_index;
    int emulate_m = 0;

    use_python_sigint();
    // Connect sys.stdout and sys.stderr to fp
    connect2fp();

    if (debug) {
        int i;
        fprintf(fp, "***options processing\n");
        for(i=0; i < argc; i++)
            fprintf(fp,"  argv[%d] = %s\n", i, argv[i]);
    }

    optind = 0;
    while ((c = getopt_long(argc, argv, "+hvpmd:",
        long_options, &option_index)) != -1) {
        switch(c) {
            case 'h':
                ep_usage();
                return;
            case 'v':
                fprintf(fp," ***  C-module Information ***\n");
                fprintf(fp,"  C-module version=%s\n", crashmod_version);
                fprintf(fp,"  crash used for build: %s\n", build_crash_version);
                // Check for other programs embedded in zipfile
                fprintf(fp, "\n --- Using %s ---\n", ext_filename);
                run_fromzip("README", ext_filename);
                return;
            case 'p':
                PyRun_SimpleString("import sys; print (sys.version); print (sys.path)");
                return;
            case 'd':
                debug = atoi(optarg);
                need_prog = 0;
                break;
            case 'm':
                emulate_m = 1;
                break;
            default: /* '?' */
                ep_usage();
                return;
        }
        }

        // Unprocessed arguments now start from optind
        if (optind == argc) {
            if (need_prog)
                fprintf(fp, " You need to specify a program file or options\n"
                "Check 'epython -h' for details\n");
            // No arguments passed
            use_crash_sigint();
            return;
        }

        /* Shift argv, argc by optind */
        nargv = argv+optind;
        argc -= optind;

        if (debug) {
            int i;
            printf(" >>> after options processed\n");
            for(i=0; i < argc; i++)
                printf("  nargv[%d] = %s\n", i, nargv[i]);
        }

        prog = find_pyprog(nargv[0]);
        if (prog) {
            if (debug)
                fprintf(fp, "  --debug-- Running %s\n", prog);
            nargv[0] = (char *) prog;		/* Is hopefully OK */
            scriptfp = fopen(prog, "r");
            /* No need to do anything if the file does not exist */
            if (scriptfp == NULL) {
                fprintf(fp, " Cannot open the file <%s>\n", prog);
                use_crash_sigint();
                return;
            } else {
                const char *rpath = realpath(prog, NULL);
                if (debug && rpath) {
                    char *pdir = dirname((char *) rpath);
                    fprintf(fp, "  --debug-- Realpath %s\n", pdir);
                    free((void *) rpath);
                }
            }
        }



        // We should add handling exceptions here to prevent 'crash' from exiting
        if (argc > 0) {
            // We need to convert char **nargv -> wchar_t **argv. We'll allocate memory
            // for that and free it after running our script
            argv_copy = (wchar_t **)PyMem_Malloc(sizeof(wchar_t*)*argc);
            /* We need a second copy, as Python might modify the first one. */
            argv_copy2 = (wchar_t **)PyMem_Malloc(sizeof(wchar_t*)*argc);
            for (i = 0; i < argc; i++) {
                argv_copy[i] = Py_DecodeLocale(nargv[i], NULL);
                if (!argv_copy[i])
                    PyErr_NoMemory();
                argv_copy2[i] = argv_copy[i];
            }
            PySys_SetArgvEx(argc, argv_copy, 0);

            /* The function will be available only on the 2nd and further invocations
             *     of epython as it is normally defined in API.py which is not loaded yet */
            if (!quiet)
                call_sys_enterepython();
            /* This is where we run the real user-provided script */
            // checksignals();
            if (scriptfp) {
                // Out subroutine emulates PyRun_SimpleFile but catches PyExc_SystemExit
                PyKdump_Run_File(scriptfp, nargv[0]);
                fclose(scriptfp);

            } else {
                /* Try to load code from ZIP */
                int rc = 0;
                if (quiet)
                    strcpy(buffer, "");	/* Initprog is in top dir */
                    else {
                        if (emulate_m)
                            strcpy(buffer, "pylib/");
                        else
                            strcpy(buffer, "progs/");
                    }

                    rc = run_fromzip(strncat(buffer, nargv[0], BUFLEN - 60), ext_filename);
                if (!rc && !quiet)
                    fprintf(fp, " Cannot find the program <%s>\n", nargv[0]);
            }
        }
        if (debug)
            fprintf(stderr, "Exiting\n");

        // Run epython exitfuncs (if registered)
        if (!quiet)
            call_sys_exitepython();
        fflush(fp);
        // Reset sys.path every time after running a program as we do not destory the intepreter
        Py_SetPath(wstdpath);

        // Free memory allocated for wchar copies
        for (i = 0; i < argc; i++) {
            PyMem_Free(argv_copy2[i]);
        }
        PyMem_Free(argv_copy);
        PyMem_Free(argv_copy2);
        if (debug)
            checksignals();
        use_crash_sigint();
        if (debug)
            checksignals();

}

void
cmd_epython() {
    epython_execute_prog(argcnt, args, 0);
}


char *help_epython[] = {
    "epython",                        /* command name */
    "invokes embedded Python interpreter",   /* short description */
    "program.py arg ...",	/* argument synopsis, or " " if none */

    "  This command invokes embedded Python.",
    "\nEXAMPLE",
    "  Output help information for 'xportshow' tool:\n",
    "    crash> epython xportshow.py --help",
    NULL
};
