/* Python extension to interact with CRASH

# --------------------------------------------------------------------
# (C) Copyright 2006-2017 Hewlett-Packard Enterprise Development LP
#
# Author: Alex Sidorenko <asid@hpe.com>
#
# --------------------------------------------------------------------  

  This program is free software; you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation; either version 2 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.
*/

#include <Python.h>
#include <stdlib.h>

#include "defs.h"    /* From the crash source top-level directory */

#include "pykdump.h"

/* Unfortuntely, we cannot replace that internal header with a nice <endian.h>
   as we need __cpu_to_le32
*/
#include <asm/byteorder.h>
//#include <endian.h>

// for FD_ISSET
#include <sys/select.h>


extern struct extension_table *epython_curext;
extern int epython_execute_prog(int argc, char *argv[], int);
extern const char *py_vmcore_realpath;

extern int debug;

static jmp_buf copy_pc_env;

/* We save the version of crash against which we build */
const char *build_crash_version = CRASHVERS;

/* crash exceptions */
PyObject *crashError;

static PyObject *m, *d;		/* Our module object and its dictionary */

/* Default memory time for readmem() */
static int default_mtype = KVADDR;

static PyObject *
py_crash_symbol_exists(PyObject *self, PyObject *args) {
  char *varname;
  int val;

  if (!PyArg_ParseTuple(args, "s", &varname)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  val = symbol_exists(varname);
  return Py_BuildValue("i", val);
}

static PyObject *
py_crash_struct_size(PyObject *self, PyObject *args) {
  char *varname;
  long val;

  if (!PyArg_ParseTuple(args, "s", &varname)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  val = STRUCT_SIZE(varname);
  return Py_BuildValue("l", val);
}

static PyObject *
py_crash_union_size(PyObject *self, PyObject *args) {
  char *varname;
  long val;

  if (!PyArg_ParseTuple(args, "s", &varname)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  val = UNION_SIZE(varname);
  return Py_BuildValue("l", val);
}

static PyObject *
py_crash_member_size(PyObject *self, PyObject *args) {
  char *name, *member;
  long val;

  if (!PyArg_ParseTuple(args, "ss", &name, &member)) {
    PyErr_SetString(crashError, "invalid parameter(s) type"); \
    return NULL;
  }

  val = MEMBER_SIZE(name, member);
  return Py_BuildValue("l", val);
}

static PyObject *
py_crash_member_offset(PyObject *self, PyObject *args) {
  char *name, *member;
  long val;

  if (!PyArg_ParseTuple(args, "ss", &name, &member)) {
    PyErr_SetString(crashError, "invalid parameter(s) type"); \
    return NULL;
  }

  val = MEMBER_OFFSET(name, member);
  return Py_BuildValue("l", val);
}

// Interface to 'crash' internal subroutine
// int enumerator_value(char *e, long *value)
// Return None if not found
static PyObject *
py_crash_enumerator_value(PyObject *self, PyObject *args) {
  char *varname;
  long val;

  if (!PyArg_ParseTuple(args, "s", &varname)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }
  if (enumerator_value(varname, &val)) {
      return PyLong_FromLong(val);
  } else {
      Py_INCREF(Py_None);
      return Py_None;
  }
}

# if 0
// This is not used anywhere but creates problems for portability
static PyObject *
py_crash_get_symbol_type(PyObject *self, PyObject *args) {
  char *name, *member = NULL;
  int val;
  struct gnu_request req;

  if (!PyArg_ParseTuple(args, "s|s", &name, &member)) {
    PyErr_SetString(crashError, "invalid parameter(s) type"); \
    return NULL;
  }

  printf("name=%s, member=%s\n", name, member);
  val = get_symbol_type(name, member, &req);
  // BUG
#if defined(GDB_5_3) || defined(GDB_6_0) || defined(GDB_6_1) || defined(GDB_7_0)
  printf("val=%d, length=%d, name=%s, typename=%s, tagname=%s\n",
	 val, (int)req.length, req.name, req.typename, req.tagname);
#else
  printf("val=%d, length=%d, name=%s, typename=%s, tagname=%s\n",
         val, (int)req.length, req.name, req.type_name, req.tagname);
#endif

  return Py_BuildValue("i", val);
}
#endif

static PyObject *
py_get_GDB_output(PyObject *self, PyObject *args) {
  char *cmd;
  char buf[BUFSIZE];

  PyObject *out = PyString_FromString("");
  PyObject *newpart;

  if (!PyArg_ParseTuple(args, "s", &cmd)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }
  if (debug > 1)
    printf("exec_gdb_command %s\n", cmd);

  // Send command to GDB and get its text output

  open_tmpfile();
  if (!gdb_pass_through(cmd, NULL, GNU_RETURN_ON_ERROR)) {
    close_tmpfile();
    Py_INCREF(Py_None);
    return Py_None;
    //error(FATAL, "gdb request failed: %s\n", cmd);
  }

  // Now read and print from fp
  rewind(pc->tmpfile);
  while (fgets(buf, BUFSIZE, pc->tmpfile)) {
    newpart = PyString_FromString(buf);
    // On Python3: PyObject* PyUnicode_Concat(PyObject *left, PyObject *right)
    // and returns a new reference
    out = PyUnicode_Concat(out, newpart);
    Py_DECREF(newpart);
    //fputs(buf, stderr);
  }

  close_tmpfile();

  //Py_INCREF(Py_None);
  return out;
}


// This command opens and writes to FIFO so we expect someone to read it
// It would be probably better to do all reading right here but at this
// moment we rely on Python part to do this
// This command does not support timeout anymore as it can create problems.
// Use exec_crash_command_bg for reliable timeouts
static int __default_timeout = 60;


static PyObject *
py_exec_crash_command(PyObject *self, PyObject *pyargs) {
  char *cmd;
  // char buf[BUFSIZE];
  FILE *oldfp = fp;
  FILE *old_stdpipe = pc->stdpipe;
  int flength;			/* Length of a temporary file */
  int rlength;
  char *tmpbuf;
  PyObject *obj;
  int no_stdout = 0;

  int internal_error = 0;	/* crash/GDB error */

  if (!PyArg_ParseTuple(pyargs, "s|i", &cmd, &no_stdout)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  if (debug > 1)
    printf("exec_crash_command <%s>\n", cmd);
  // Send command to crash and get its text output

  // ***** Enable CRASH SIGINT handler. If we press ^C in this state, 
  // we will get crash.error exception
  use_crash_sigint();
  
  strcpy(pc->command_line, cmd);
  clean_line(pc->command_line);
  strcpy(pc->orig_line, pc->command_line);
  strip_linefeeds(pc->orig_line);

  argcnt = parse_line(pc->command_line, args);
  fflush(fp);

  fp = tmpfile();


  /*
    crash uses longjmp(pc->main_loop_env) to recover after some errors.
    This puts us into its main loop: read line/process command. As we
    don't want this, we'll replace pc->main_loop_env with our own location,
    and later will restore it.
   */

  // Copy the old location
  memcpy(copy_pc_env, pc->main_loop_env, sizeof(jmp_buf));
  if (!setjmp(pc->main_loop_env)) {
    // Suppress output to stdout if stdpipe is NULL
    if (!pc->stdpipe && no_stdout)
        pc->stdpipe = pc->nullfp;
    exec_command();
    if (no_stdout)
        pc->stdpipe = old_stdpipe;
    free_all_bufs();
  } else {
    // There was an internal GDB/crash error
    internal_error = 1;
  }

  // Make pc->main_loop_env point to its original location
  memcpy(pc->main_loop_env, copy_pc_env, sizeof(jmp_buf));

  // Now read from the temporary file
  fflush(fp);
  flength = ftell(fp);
  fseek(fp, 0,0);
  tmpbuf = malloc(flength);
  rlength =  fread(tmpbuf, 1, flength, fp);
  obj = PyString_FromStringAndSize(tmpbuf, flength);
  free(tmpbuf);

  fclose(fp);
  fp = oldfp;

  use_python_sigint();
  // If there was an error, we raise an exception
  // and pass text gathered so far
  if (internal_error || rlength == 0) {
    PyErr_SetObject(crashError, obj);
    return NULL;
  }

  return obj;
}


// We need to reopen vmcore. Unfortunately, we cannot get its FD from
// 'crash' at this moment
// Find fd based on the filename. Returns fd=-1 if we cannot find a match


#define _MAXPATH 400
int fn2fd(const char *rpath) {
  static const char *selffd = "/proc/self/fd/";
  char buf[_MAXPATH];
  struct dirent *de;
  DIR *dirp;
  char *linkname;
  struct stat sb;
  int nbytes;
  int foundfd = -1;
  int selffdlen = strlen(selffd);
  int linknamesz;

  dirp = opendir(selffd);

  // The following does not work as /proc is not POSIX-compliant!
  //linknamesz = sb.st_size + 1;
  linknamesz = PATH_MAX;
  linkname = (char *)malloc(linknamesz);

  while ((de = readdir(dirp))) {
    char *dname = de->d_name;
    int lfd;

    if (strcmp(dname, ".") == 0 || strcmp(dname, "..") == 0)
      continue;
    strncpy(buf, selffd, _MAXPATH-1);
    strncpy(buf+selffdlen, dname, _MAXPATH-selffdlen-1);
    if (lstat(buf, &sb) == -1)
      continue;

    //if ((nbytes = readlink(buf, linkname, sb.st_size + 1)) >0) {
    if ((nbytes = readlink(buf, linkname, linknamesz-1)) >0) {
      lfd = atoi(dname);
      linkname[nbytes] = '\0';
      //printf("fdf =%d %s %s\n", lfd, dname, linkname);
      if (strcmp(linkname, rpath) == 0) {
          foundfd = lfd;
          break;
      }
    }
  }  /* while */
  free((void *)linkname);
  return foundfd;
}


// Start executing crash command in a separate thread
// Return (fileno, pid) where fileno is an OS-level fd to read from
// We don't provide an argument for timeout here as it can be
// implemented doing select on fd

static PyObject *
py_exec_crash_command_bg2(PyObject *self, PyObject *pyargs) {
  char *cmd;
  int pipefd[2];		 /* For files redirection */
  int pid;

  int dfd;                      /* FD used to read vmcore */
  static int fd = -1;           /* Original FD used by crash */

  unsigned long long saved_flags; /* To save pc->flags */

  if (!PyArg_ParseTuple(pyargs, "s", &cmd)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  if (debug > 1)
    printf("exec_crash_command_bg2 <%s>\n", cmd);

  // Disable scroll pager
  saved_flags = pc->flags;
  pc->flags &= ~SCROLL;

  if (pipe(pipefd) == -1) {
    PyErr_SetString(crashError, "cannot create a pipe");
    return NULL;
  }

  if (fd == -1) {
      fd = fn2fd(py_vmcore_realpath);

      if (fd == -1) {
          PyErr_SetString(crashError, "cannot find vmcore fd");
          return NULL;
      }
  }
  // We execute crash command in another thread (forked) and read its output
  //printf(" Before fork: sockfd, nfd, mfd, kfd, dfd %d, %d,%d,%d,%d\n",
  //       pc->sockfd, pc->nfd, pc->mfd, pc->kfd, pc->dfd);
  pid = fork();

  if (pid == -1) {
    PyErr_SetString(crashError, "cannot fork()");
    return NULL;
  }


  if (pid == 0) {
    /* A Child */
    // crash does lseek on fd opened for vmcore. If we want to run
    // multiple copies of this command simultaneously, we need to
    // reopen this file. The descriptor of interest is :
    // Normally pc->dfd
    // The file name is pc->dumpfile
    off_t cpos;
    int rc;
    cpos =  lseek(fd, 0, SEEK_CUR);

    dfd = open(py_vmcore_realpath, O_RDONLY);
    rc = dup2(dfd, fd);
    close(dfd);

    lseek(fd, cpos, SEEK_SET);
    if (debug)
      printf("Reopening %d %s rc=%d\n", fd, py_vmcore_realpath, rc);


    // Child writes to pipe
    close(pipefd[0]);          /* Close unused read end */
    // Convert FD to 'fp'
    fflush(fp);
    dup2(pipefd[1], fileno(fp));
    close(pipefd[1]);
    setlinebuf(fp);

    // Dup stdout to stderr
    /*
    dup2(pipefd[1], fileno(fp));

    fprintf(stderr, "\n**stderr**\n");
    */



    // Prepare the command line for crash
    strcpy(pc->command_line, cmd);
    clean_line(pc->command_line);
    strcpy(pc->orig_line, pc->command_line);
    strip_linefeeds(pc->orig_line);

    argcnt = parse_line(pc->command_line, args);

    /*
      crash uses longjmp(pc->main_loop_env) to recover after some errors.
      This puts us into its main loop: read line/process command. As we
      don't want this, we'll replace pc->main_loop_env with our own location,
      and later will restore it.
    */

    // We return success/failure as exit code
    if (!setjmp(pc->main_loop_env)) {
      extern int _unload_epython;
      exec_command();
      free_all_bufs();
      _unload_epython = 0;
      exit(0);
    } else {
      // There was an internal GDB/crash error
      exit(1);
    }
  }

  /* --------- Parent - read from pipe ------------- */

  // Read from pipe
  close(pipefd[1]);          /* Close unused write end */

  // Restore pc->flags
  pc->flags = saved_flags;

  // Return a tuple of two integers: (fileno, pid)
  return Py_BuildValue("(ii)", pipefd[0], pid);
}

// Call epython_execute_prog(argc, argv, 0)
static PyObject *
py_exec_epython_command(PyObject *self, PyObject *pyargs) {
  int argc = PyTuple_Size(pyargs);
  int i;

  char **argv = (char **) malloc(sizeof(char *) * argc);

  for (i=0; i < argc; i++)
    argv[i] = PyString_AsString(PyTuple_GetItem(pyargs, i));
  epython_execute_prog(argc, argv, 0);
  free(argv);

  Py_INCREF(Py_None);
  return Py_None;
}

static PyObject *
py_sym2addr(PyObject *self, PyObject *args) {
  char *symbol;
  unsigned long long addr;
  struct syment *se;
 
  if (!PyArg_ParseTuple(args, "s", &symbol)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  se = symbol_search(symbol);

  if (se)
    addr = se->value;
  else
    addr = 0;

  // ASID
  //printf("addr=%lx\n", addr);
  //return Py_BuildValue("K", (unsigned long long) addr);
  return PyLong_FromUnsignedLong(addr);
}


extern  struct syment * symbol_search_next(char *, struct syment *);


static PyObject *
py_sym2_alladdr(PyObject *self, PyObject *args) {
  char *symbol;
  unsigned long long addr;
  struct syment *se;
  PyObject *list;

  if (!PyArg_ParseTuple(args, "s", &symbol)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  se = symbol_search(symbol);

  if (se)
    addr = se->value;
  else
    addr = 0;

  list = PyList_New(0);
  if (addr)
    if (PyList_Append(list,PyLong_FromUnsignedLong(addr)) == -1)
      return NULL;

  // Are there additional symbols?
  while ((se = symbol_search_next(symbol, se)))
    if (PyList_Append(list,PyLong_FromUnsignedLong(se->value)) == -1)
      return NULL;
  // ASID
  //printf("addr=%lx\n", addr);
  //return Py_BuildValue("K", (unsigned long long) addr);
  return list;
}

static PyObject *
py_addr2sym(PyObject *self, PyObject *args) {
  // char *symbol;
  unsigned long addr;
  ulong offset;
  int loose_match = 0;

  struct syment *se;

  if (!PyArg_ParseTuple(args, "k|i", &addr,&loose_match)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  se = value_search(addr, &offset);

  if (loose_match) {
    if (se)
      return Py_BuildValue("sk", se->name, offset);
    else
      return Py_BuildValue("ss", NULL, NULL);
  } else {
    if (se && offset == 0)
      return Py_BuildValue("s", se->name);
    else
      return Py_BuildValue("s", NULL);
  }
}

static PyObject *
py_addr2mod(PyObject *self, PyObject *args) {
  // char *symbol;
  unsigned long addr;
  int loose_match = 0;

  struct load_module *lm;
  if (!PyArg_ParseTuple(args, "k|i", &addr,&loose_match)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }
  
  if (module_symbol(addr, NULL, &lm, NULL, 0))
    return Py_BuildValue("s", lm->mod_name);
  else {
    Py_INCREF(Py_None);
    return Py_None;
  }
}



// A switch table - call the needed function based on integer object
// size

typedef PyObject * (*conversion_func)(const char *p);
static conversion_func functable_signed[16];
static conversion_func functable_usigned[16];


#if 0
// The following nu_xxxx routines are copied from Python's 'structmodule.c'
static PyObject *
nu_char(const char *p)
{
        return PyString_FromStringAndSize(p, 1);
}
#endif

static PyObject *
nu_byte(const char *p)
{
        return PyInt_FromLong((long) *(signed char *)p);
}

static PyObject *
nu_ubyte(const char *p)
{
        return PyInt_FromLong((long) *(unsigned char *)p);
}

static PyObject *
nu_short(const char *p)
{
        short x;
        memcpy((char *)&x, p, sizeof x);
        return PyInt_FromLong((long)x);
}

static PyObject *
nu_ushort(const char *p)
{
        unsigned short x;
        memcpy((char *)&x, p, sizeof x);
        return PyInt_FromLong((long)x);
}

static PyObject *
nu_int(const char *p)
{
        int x;
        memcpy((char *)&x, p, sizeof x);
        return PyInt_FromLong((long)x);
}

static PyObject *
nu_uint(const char *p)
{
        unsigned int x;
        memcpy((char *)&x, p, sizeof x);
        return PyLong_FromUnsignedLong((unsigned long)x);
}

static PyObject *
nu_long(const char *p)
{
        long x;
        memcpy((char *)&x, p, sizeof x);
        return PyInt_FromLong(x);
}

static PyObject *
nu_ulong(const char *p)
{
        unsigned long x;
        memcpy((char *)&x, p, sizeof x);
        return PyLong_FromUnsignedLong(x);
}

/* Native mode doesn't support q or Q unless the platform C supports
   long long (or, on Windows, __int64). */

#ifdef HAVE_LONG_LONG

static PyObject *
nu_longlong(const char *p)
{
        PY_LONG_LONG x;
        memcpy((char *)&x, p, sizeof x);
        return PyLong_FromLongLong(x);
}

static PyObject *
nu_ulonglong(const char *p)
{
        unsigned PY_LONG_LONG x;
        memcpy((char *)&x, p, sizeof x);
        return PyLong_FromUnsignedLongLong(x);
}

#endif

#if 0
static PyObject *
nu_float(const char *p)
{
        float x;
        memcpy((char *)&x, p, sizeof x);
        return PyFloat_FromDouble((double)x);
}

static PyObject *
nu_double(const char *p)
{
        double x;
        memcpy((char *)&x, p, sizeof x);
        return PyFloat_FromDouble(x);
}
#endif

static PyObject *
nu_void_p(void *p)
{
  //void *x;
  //memcpy((char *)&x, p, sizeof x);
  // The next line works incorrectly as it produces a signed value
  //return PyLong_FromVoidPtr(x);
  return functable_usigned[sizeof(void *)-1](p);
}

static PyObject *
nu_badsize(const char *p) {
  PyErr_SetString(crashError, "bad size");
  return NULL;
}




static PyObject *
py_mem2long(PyObject *self, PyObject *args, PyObject *kwds) {
  char *str;
  int size;
  // unsigned long addr;

  static char *kwlist[] = {"source", "signed", "array", NULL};
  int array = 0;
  int signedvar = 0;

  if (!PyArg_ParseTupleAndKeywords(args, kwds, "s#|ii", kwlist,
				   &str, &size,
				   &signedvar, &array)) {
    //PyErr_SetString(crashError, "invalid parameter type");
    return NULL;
  }

  //printf("strsize=%d, signed=%d, array=%d\n",size, signedvar, array);

  if (array <= 1) {
    if (size < 0 || (unsigned) size > sizeof(functable_signed)/sizeof(conversion_func))
      return nu_badsize(str);
    if (signedvar)
      return functable_signed[size-1](str);
    else
      return functable_usigned[size-1](str);
  } else {
    /* We have an array */
    int sz1 = size/array;
    int i;
    PyObject *list, *val;
    if (size < 0 || sz1*array != size ||
	(unsigned)sz1 > sizeof(functable_signed)/sizeof(conversion_func))
      return nu_badsize(str);

    list = PyList_New(0);
    for (i=0; i < array; i++) {
      if (signedvar)
	val = functable_signed[sz1-1](str + sz1*i);
      else
	val = functable_usigned[sz1-1](str + sz1 * i);
      if (PyList_Append(list, val) == -1)
	return NULL;
    }
    return list;
  }
  return NULL;
}

static PyObject *
py_readPtr(PyObject *self, PyObject *args) {
  void *p;
  ulonglong addr;
  // int size;
  // void *buffer;
  char pb[256];

  // PyObject *out;

  PyObject *arg1 = PyTuple_GetItem(args, 0);
  int mtype = default_mtype;
  if (PyTuple_Size(args) > 1)
    mtype = PyInt_AsLong(PyTuple_GetItem(args, 1));

  addr = PyLong_AsUnsignedLongLong(arg1);
  /* When we see a NULL pointer we raise not a crash-specific
     exception but rather IndexError. This is useful as we often
     need to detect NULL pointers, e.g. the end of list marker
  */
  if (!addr) {
    sprintf(pb, "readPtr NULL pointer");
    PyErr_SetString(PyExc_IndexError, pb);
    return NULL;
  }
  if (readmem(addr, mtype, &p, sizeof(void *), "Python",
	      RETURN_ON_ERROR|QUIET) == FALSE) {
    sprintf(pb, "readmem error at addr 0x%llx", addr);
    PyErr_SetString(crashError, pb);
    return NULL;

  }
  return nu_void_p(&p);
}



//int readmem(ulonglong addr, int memtype, void *buffer, long size,
//	char *type, ulong error_handle)

// With Python2, we return a 'str' object
// With Python3, we return a 'bytes' object

static PyObject *
py_readmem(PyObject *self, PyObject *args) {
  char pb[256];
  // char *symbol;
  ulonglong addr;
  long size;
  void *buffer;

  PyObject *out;

  PyObject *arg1 = PyTuple_GetItem(args, 0);
  PyObject *arg2 = PyTuple_GetItem(args, 1);
  int mtype = default_mtype;
  if (PyTuple_Size(args) > 2)
    mtype = PyInt_AsLong(PyTuple_GetItem(args, 2));

  /* This is buggy on 64-bit - sign is incorrect
  if (!PyArg_ParseTuple(args, "kl", &addr, &size)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }
  */
  // With Python3, integers are always long
  addr = PyLong_AsUnsignedLongLong(arg1);
  size = PyLong_AsLong(arg2);

  /* When we see a NULL pointer we raise not a crash-specific
     exception but rather IndexError. This is useful as we often
     need to detect NULL pointers, e.g. the end of list marker
  */

  if (!addr) {
    sprintf(pb, "readPtr NULL pointer");
    PyErr_SetString(PyExc_IndexError, pb);
    return NULL;
  }

  buffer = (void *) malloc(size);
  // printf("trying to read %ld bytes from %p %p\n", size, addr, buffer);
  if (readmem(addr, mtype, buffer, size, "Python",
	      RETURN_ON_ERROR|QUIET) == FALSE) {
    sprintf(pb, "readmem error at addr 0x%llx, reading %ld bytes", addr, size);
    PyErr_SetString(crashError, pb);
    return NULL;

  }
  out = PyBytes_FromStringAndSize(buffer, size);
  free(buffer);
  return out;
}

/* Read an integer (not an array of integers)
   To improve the performance, we assume that sizeof of any integer is not
   greater than 32 and use a predefined buffer for that

   Args: addr, size, signed (False/True)
*/
static PyObject *
py_readInt(PyObject *self, PyObject *args) {
  // char *symbol;
  ulonglong addr;
  long size;
  int signedvar = 0;		/* The default */
  int mtype = default_mtype;
  char buffer[32];

  // PyObject *out;

  PyObject *arg1 = PyTuple_GetItem(args, 0);
  PyObject *arg2 = PyTuple_GetItem(args, 1);

  if (PyTuple_Size(args) > 2)
    signedvar = PyInt_AsLong(PyTuple_GetItem(args, 2));

  addr = PyLong_AsUnsignedLongLong(arg1);
  size = PyLong_AsLong(arg2);

  if (size > 32) {
    char pb[256];
    sprintf(pb, "readInt cannot read reading %ld bytes", size);
    PyErr_SetString(crashError, pb);
    return NULL;
  }

  if (readmem(addr, mtype, buffer, size, "Python",
	      RETURN_ON_ERROR|QUIET) == FALSE) {
    char pb[256];
    sprintf(pb, "readmem/py_readInt error at addr 0x%llx, reading %ld bytes",
	    addr, size);
    PyErr_SetString(crashError, pb);
    return NULL;

  }
  if (size < 0 || (unsigned) size > sizeof(functable_signed)/sizeof(conversion_func))
    return nu_badsize(buffer);
  if (signedvar)
    return functable_signed[size-1](buffer);
  else
    return functable_usigned[size-1](buffer);
}


/*
  Set default readmem operations to use UVADDR for task
  readmem_task(taskaddr)  - set to UVADDR and set the current context
  readmem_task(0)           - reset to KVADDR
*/
static PyObject *
py_readmem_task(PyObject *self, PyObject *args) {
  ulong tskaddr;
  struct task_context *task;
  static struct task_context *prev_task = NULL;

  PyObject *arg0 = PyTuple_GetItem(args, 0);

  // Wtih Python3, integers are always long
  tskaddr = PyLong_AsUnsignedLongLong(arg0);

  if (tskaddr) {
    task = task_to_context(tskaddr);
    if (!task) {
      PyErr_SetString(crashError, "bad taskaddr"); \
      return NULL;
    }
    prev_task = tt->current;
    tt->current = task;
    default_mtype = UVADDR;
  } else {
    default_mtype = KVADDR;
    if (prev_task)
      tt->current = prev_task;
  }
  Py_INCREF(Py_None);
  return Py_None;
}


/*
   Copied from crash/kernel.c - it is declared as static there,
   so we have to duplicate
 */
static int
get_NR_syscalls(void)
{
        ulong sys_call_table;
        struct syment *sp;
        int cnt;

        sys_call_table = symbol_value("sys_call_table");
        if (!(sp = next_symbol("sys_call_table", NULL)))
                return 256;

        while (sp->value == sys_call_table) {
                if (!(sp = next_symbol(sp->name, NULL)))
                        return 256;
        }

        if (machine_type("S390X"))
                cnt = (sp->value - sys_call_table)/sizeof(int);
        else
                cnt = (sp->value - sys_call_table)/sizeof(void *);

        return cnt;
}

static PyObject *
py_get_NR_syscalls(PyObject *self, PyObject *args) {
    return PyInt_FromLong(get_NR_syscalls());
}

/*
  physaddr = uvtop(tskaddr, vaddr)
*/

static PyObject *
py_uvtop(PyObject *self, PyObject *args) {
  physaddr_t physaddr;
  ulong tskaddr, vaddr;
  int verbose = 0;

  PyObject *arg0 = PyTuple_GetItem(args, 0);
  PyObject *arg1 = PyTuple_GetItem(args, 1);

  tskaddr = PyLong_AsUnsignedLong(arg0);
  vaddr = PyLong_AsUnsignedLong(arg1);

  // uvtop(struct task_context *tc,ulong vaddr,physaddr_t *paddr,int verbose)

  if (!uvtop(task_to_context(tskaddr), vaddr, &physaddr, verbose)) {
    // We cannot convert
    char pb[256];
    sprintf(pb, "uvtop error at vaddr 0x%llx", (long long unsigned) vaddr);
    PyErr_SetString(crashError, pb);
    return NULL;
  }

  return PyLong_FromUnsignedLongLong((ulonglong)physaddr);
}
 
/*
  page = phys_to_page(physaddr_t phys)
*/

static PyObject *
py_phys_to_page(PyObject *self, PyObject *args) {
  physaddr_t physaddr;
  ulong page;

  PyObject *arg0 = PyTuple_GetItem(args, 0);

  physaddr = PyLong_AsUnsignedLong(arg0);

  //int phys_to_page(physaddr_t phys, ulong *pp)

  if (!phys_to_page(physaddr, &page)) {
    // We cannot convert
    char pb[256];
    sprintf(pb, "phys_to_page error at physaddr 0x%llx", (long long unsigned) physaddr);
    PyErr_SetString(crashError, pb);
    return NULL;
  }

  return PyLong_FromUnsignedLongLong((ulonglong)page);
}

static PyObject *
py_pageoffset(PyObject *self, PyObject *args) {
  ulong vaddr;

  if (!PyArg_ParseTuple(args, "k", &vaddr)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  return PyLong_FromUnsignedLong(PAGEOFFSET(vaddr));
}



static PyObject *
py_getFullBuckets(PyObject *self, PyObject *args) {
  ulonglong start;
  int bsize, items, chain_off;

  char *buffer;

  PyObject* list;
  void *bucket;
  int i;

  if (!PyArg_ParseTuple(args, "Kiii",
			&start,
			&bsize, &items, &chain_off)) {
     PyErr_SetString(crashError, "bad arguments");
    return NULL;
  }

  buffer = (void *) malloc(bsize*items);
  if (!buffer) {
    PyErr_SetString(crashError, "cannot malloc");
    return NULL;
  }
  //printf("start=0x%llx, bsize=%d items=%d  chain_off=%d\n",
  //	 start, bsize, items, chain_off);
  //readmem(start, KVADDR, buffer, bsize*items, "Python", FAULT_ON_ERROR);
  if (readmem(start, KVADDR, buffer, bsize*items, "Python",
	      RETURN_ON_ERROR|QUIET) == FALSE) {
    char pb[256];
    sprintf(pb, "readmem error at addr 0x%llx", start);	\
    PyErr_SetString(crashError, pb);
    return NULL;

  }
  list = PyList_New(0);
  for (i=0; i < items; i++) {
        memcpy((char *)&bucket, buffer+i*bsize+chain_off, sizeof bucket);
	if (bucket) {
	  PyList_Append(list, PyLong_FromUnsignedLong((unsigned long)bucket));
	}
  }
  free(buffer);
  return list;
}

static PyObject *
py_getFullBuckets_h(PyObject *self, PyObject *args) {
  ulonglong start;
  int bsize, items, chain_off;

  char *buffer;

  PyObject* list;
  void *bucket;
  int i;

  if (!PyArg_ParseTuple(args, "Kiii",
                        &start,
                        &bsize, &items, &chain_off)) {
     PyErr_SetString(crashError, "bad arguments");
    return NULL;
  }

  buffer = (void *) malloc(bsize*items);
  if (!buffer) {
    PyErr_SetString(crashError, "cannot malloc");
    return NULL;
  }
  //printf("start=0x%llx, bsize=%d items=%d  chain_off=%d\n",
  //     start, bsize, items, chain_off);
  //readmem(start, KVADDR, buffer, bsize*items, "Python", FAULT_ON_ERROR);
  if (readmem(start, KVADDR, buffer, bsize*items, "Python",
              RETURN_ON_ERROR|QUIET) == FALSE) {
    char pb[256];
    sprintf(pb, "readmem error at addr 0x%llx", start); \
    PyErr_SetString(crashError, pb);
    return NULL;

  }
  list = PyList_New(0);
  for (i=0; i < items; i++) {
      PyObject *el;
        memcpy((char *)&bucket, buffer+i*bsize+chain_off, sizeof bucket);
        if (bucket) {
          /* Python 2.4.3 has PyLong_FromVoidPtr but it converts to Int with
             sign - a bug, need report this to Python team */
          el = Py_BuildValue("(ik)", i, ((unsigned long)bucket));
          PyList_Append(list, el);
          //PyList_Append(list, PyLong_FromUnsignedLong((unsigned long)bucket));
        }
  }
  free(buffer);
  return list;
}

/* Find a total number of elements in a list specified with addr, offset
   Usage: count = getListSize(addr, offset, maxel = 1000)
   We do not include the list_head
*/

static PyObject *
py_getlistsize(PyObject *self, PyObject *args) {
  char *addr;
  long offset;
  long maxel;

  char pb[256];

  int count = 0;
  char *ptr, *next;

  PyObject *arg0 = PyTuple_GetItem(args, 0);
  PyObject *arg1 = PyTuple_GetItem(args, 1);
  PyObject *arg2 = PyTuple_GetItem(args, 2);

  ptr = addr = (char *) PyLong_AsUnsignedLong(arg0);
  offset = PyLong_AsLong(arg1);
  maxel = PyLong_AsLong(arg2);

  // readmem(ulonglong addr, int memtype, void *buffer, long size,
  //         char *type, ulong error_handle)
  while (ptr && count < maxel) {
    /* next = readPtr(ptr+offset) */
    if (readmem((ulonglong)(ulong)(ptr + offset), KVADDR, &next,
		sizeof(void *), "Python", RETURN_ON_ERROR|QUIET) == FALSE) {
          sprintf(pb, "readmem error at addr %p", addr);	\
	  PyErr_SetString(crashError, pb);
	  return NULL;
    }

    //printf("addr=%p next=%p\n", addr, next);
    if (next == addr)
      break;
    ptr = next;
    count++;
  }
  return PyInt_FromLong(count);
}

static PyObject *
py_FD_ISSET(PyObject *self, PyObject *args) {
  char *str;
  int fd, lstr;

  if (!PyArg_ParseTuple(args, "is#", &fd, &str, &lstr)) {
    PyErr_SetString(crashError, "invalid parameter type");
    return NULL;
  }

  return Py_BuildValue("i", FD_ISSET(fd, (fd_set *)str));
}


static PyObject *
py_sLong(PyObject *self, PyObject *args) {
  ulong val;

  PyObject *arg0 = PyTuple_GetItem(args, 0);
  val = PyLong_AsUnsignedLong(arg0);
  return nu_long((const char *) &val);
}

static PyObject *
py_le32_to_cpu(PyObject *self, PyObject *args) {
  ulong val;

  if (!PyArg_ParseTuple(args, "k", &val)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  return PyLong_FromUnsignedLong(__le32_to_cpu(val));
}

static PyObject *
py_le16_to_cpu(PyObject *self, PyObject *args) {
  ulong val;

  if (!PyArg_ParseTuple(args, "k", &val)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  //PyObject *arg0 = PyTuple_GetItem(args, 0);
  //val = PyLong_AsUnsignedLong(arg0);
  return PyLong_FromUnsignedLong(__le16_to_cpu(val));
}

#if 0
static PyObject *
py_cpu_to_le32(PyObject *self, PyObject *args) {
  ulong val;

  if (!PyArg_ParseTuple(args, "k", &val)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }


  return PyLong_FromUnsignedLong(__cpu_to_le32(val));
}
#endif


/*
  Register epython program as crash extension. Both arguments are strings
  register_epython_prog(cmd, help)
*/

static void
epython_subcommand(void) {
  int i;
  char **argv = (char **) malloc(sizeof(char *) * (argcnt + 1));
  argv[0] = "epython_subcommand";
  for (i=0; i < argcnt; i++)
    argv[i+1] = args[i];

  epython_execute_prog(argcnt+1, argv, 0);
  free(argv);
}


static PyObject *
py_register_epython_prog(PyObject *self, PyObject *args) {
  //char *cmd, *short_description, *synopsis, *help;
  char *help_data[4];
  char *cmd;
  // long val;
  int i;
  int totlen;
  // struct command_table_entry *cp;

  int nentries;

  struct command_table_entry *ct = epython_curext->command_table;
  struct command_table_entry *ce;


  if (!PyArg_ParseTuple(args, "ssss", &help_data[0],
			&help_data[1],  &help_data[2],
			&help_data[3])) {
    PyErr_SetString(crashError, "invalid parameter(s) type"); \
    return NULL;
  }

  cmd = help_data[0];
  if (debug > 1)
    printf("Registering %s\n", cmd);

  /* Check for name clash */
  if (get_command_table_entry(cmd)) {
    error(INFO, "%s: \"%s\" is a duplicate of a currently-existing command\n",
	  pc->curext->filename, cmd);
    Py_RETURN_FALSE;
  }

  if (is_alias(cmd)) {
    error(INFO,  "alias \"%s\" deleted: name clash with extension command\n",
	  cmd);
    deallocate_alias(cmd);
  }


  /* Epython's command_table is already registered. Instead of using
     a static table of predefined big size, we use realloc as needed
  */

  for(ce=ct, nentries = 0; ce->name; ce++, nentries++);

  if (debug > 1)
    printf("nentries=%d\n", nentries);

  ct = realloc(ct, sizeof(struct command_table_entry)*(nentries+2));
  if (!ct) {
    printf("Cannot realloc while registering epython/%s\n", cmd);
  } else {
    // Add a new entry
    ce = ct + nentries;
    // Alloc memory for name
    ce->name = (char *) malloc(strlen(cmd) + 1);
    if (ce->name)
      strcpy(ce->name, cmd);
    else {
      printf("malloc() failed in py_register_epython_prog\n");
      free(ct);
      return PyErr_NoMemory();
    }
    ce->func = epython_subcommand;

    totlen = 5 * sizeof(char *);
    for (i=0; i < 4; i++)
      totlen += (strlen(help_data[i]) + 1);
    ce->help_data = (char **) malloc(totlen);
    if (!ce->help_data) {
      printf("malloc() failed for help_data in py_register_epython_prog\n");
    } else {
      char **aptr = ce->help_data;
      char *sptr = (char *) (aptr + 5);
      for (i=0; i < 4; i++) {
	// int l = strlen(help_data[i]);
	*aptr++ = sptr;
	strcpy(sptr, help_data[i]);
	sptr += strlen(help_data[i]) + 1;
      }
      *aptr = NULL;
    }
    ce->flags = 0;

    // Put the new EOT marker
    (ce+1)->name = NULL;

    // Update the table in crash
    epython_curext->command_table = ct;
  }

  // Print cmd table for debugging
  if (debug > 1) {
    printf("--- Current command table ---\n");
    for (ce = epython_curext->command_table; ce->name; ce++) {
      printf("name=%s\n", ce->name);
    }
  }

  Py_RETURN_TRUE;
}

// Return the list of epython registered commands


/* Set default timeout value for exec_crash_command */
static PyObject *
py_get_epython_cmds(PyObject *self, PyObject *args) {
  struct command_table_entry *ce;
  PyObject *list, *val;
  list = PyList_New(0);
  for (ce = epython_curext->command_table; ce->name; ce++) {
    val = PyString_FromString(ce->name);
    if (PyList_Append(list, val) == -1)
      return NULL;
  }
  return list;
}

/* Set default timeout value for exec_crash_command */
static PyObject *
py_set_default_timeout(PyObject *self, PyObject *args) {
  int old_value = __default_timeout;
  if (!PyArg_ParseTuple(args, "i", &__default_timeout)) {
    PyErr_SetString(crashError, "invalid parameter type");
    __default_timeout = old_value;
    return NULL;
  }
  return PyInt_FromLong((long) old_value);
}

static PyObject *
py_get_pathname(PyObject *self, PyObject *args) {

  ulong dentry, vfsmnt;
  char pathname[BUFSIZE];
  if (!PyArg_ParseTuple(args, "kk", &dentry, &vfsmnt)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  get_pathname(dentry, pathname, sizeof(pathname), 1, vfsmnt);
  return PyString_FromString(pathname);
}

// Check whether task is active by calling crash internal subroutine
static PyObject *
py_is_task_active(PyObject *self, PyObject *args) {
  ulong taskaddr;
  long rc;
  if (!PyArg_ParseTuple(args, "k", &taskaddr)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  rc = is_task_active(taskaddr);
  return PyBool_FromLong(rc);
}

// Map task to pid calling crash() internal subroutine
static PyObject *
py_task_to_pid(PyObject *self, PyObject *args) {
  ulong taskaddr;
  ulong pid;
  if (!PyArg_ParseTuple(args, "k", &taskaddr)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  /* On error, it returns NO_PID   ((ulong)-1) */
  tt->refresh_task_table();
  pid = task_to_pid(taskaddr);

  //printf("%lu  %lu\n", taskaddr, NO_PID);
  if (pid == NO_PID) {
    Py_INCREF(Py_None);
    return Py_None;
  } else
    return PyLong_FromUnsignedLong(pid);
}

// Map pid to task calling crash() internal subroutine
static PyObject *
py_pid_to_task(PyObject *self, PyObject *args) {
  ulong taskaddr;
  ulong pid;
  if (!PyArg_ParseTuple(args, "k", &pid)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  tt->refresh_task_table();
  taskaddr = pid_to_task(pid);
  return PyLong_FromUnsignedLong(taskaddr);
}

// char *get_uptime(char *buf, ulonglong *j64p)
// Return uptime in jiffies - as returned by crash subroutine
static PyObject *
py_get_uptime(PyObject *self, PyObject *args) {
  ulonglong jiffies;

  get_uptime(NULL, &jiffies);
  return PyLong_FromUnsignedLongLong(jiffies);
}

// Interfaces to crash built-in get_task_mem_usage()
// Return a tuple (VSZ, RSS) for a given task
static PyObject *
py_get_task_mem_usage(PyObject *self, PyObject *args) {
  ulong task;
  struct task_mem_usage tm;
  unsigned long rss, total_vm;
  
  if (!PyArg_ParseTuple(args, "k", &task)) {
    PyErr_SetString(crashError, "invalid parameter type"); \
    return NULL;
  }

  get_task_mem_usage(task, &tm);
  total_vm = (tm.total_vm * PAGESIZE())/1024;
  rss = (tm.rss * PAGESIZE())/1024;

  // printf("rss=%lu total_vm=%lu\n", rss, total_vm);

  return Py_BuildValue("(kk)", total_vm, rss);
}


/* Used for changing Discovery daemon name */

#include <sys/prctl.h>

/* Unfortunately, we cannot use standard approach based on 'environ'
 * variable as it has already been relocated by crash/GDB. The only
 * thing we can do is to scan argv area and rewrite it.
 */

static int get_argv_size(void) {
    char buf[8192];
    int fd = open("/proc/self/cmdline", O_RDONLY);
    int size = read(fd, buf, 8192);
    return size;
}

static PyObject *
py_setprocname(PyObject *self, PyObject *args) {
    char *name;
    char *argv0 = pc->program_path;
    unsigned int size;

    if (!PyArg_ParseTuple(args, "s", &name))
            return NULL;

    size = get_argv_size();

    memset(argv0, '\0', size);
    strncpy(argv0, name, size-1);
    //snprintf(argv0, size - 1, name);

    prctl (15 /* PR_SET_NAME */, name, 0, 0, 0);
    Py_INCREF(Py_None);
    return Py_None;
};


PyObject * py_gdb_typeinfo(PyObject *self, PyObject *args);
PyObject * py_gdb_whatis(PyObject *self, PyObject *args);
void py_gdb_register_enums(PyObject *m);


static PyMethodDef crashMethods[] = {
  {"symbol_exists",  py_crash_symbol_exists, METH_VARARGS},
  {"struct_size",  py_crash_struct_size, METH_VARARGS},
  {"union_size",  py_crash_union_size, METH_VARARGS},
  {"member_offset",  py_crash_member_offset, METH_VARARGS},
  {"member_size",  py_crash_member_size, METH_VARARGS},
  {"enumerator_value", py_crash_enumerator_value,  METH_VARARGS},
  //  {"get_symbol_type",  py_crash_get_symbol_type, METH_VARARGS},
  {"get_GDB_output",  py_get_GDB_output, METH_VARARGS},
  {"exec_crash_command",  py_exec_crash_command, METH_VARARGS},
  {"exec_crash_command_bg2",  py_exec_crash_command_bg2, METH_VARARGS},
  {"exec_epython_command",  py_exec_epython_command, METH_VARARGS},
  {"get_epython_cmds",  py_get_epython_cmds, METH_VARARGS},
  {"sym2addr",  py_sym2addr, METH_VARARGS},
  {"sym2alladdr", py_sym2_alladdr, METH_VARARGS},
  {"addr2sym",  py_addr2sym, METH_VARARGS},
  {"addr2mod",  py_addr2mod, METH_VARARGS},
  {"mem2long",  (PyCFunction)py_mem2long, METH_VARARGS | METH_KEYWORDS},
  {"uvtop",  py_uvtop, METH_VARARGS},
  {"phys_to_page", py_phys_to_page, METH_VARARGS},
  {"PAGEOFFSET",  py_pageoffset, METH_VARARGS},
  {"readmem", py_readmem, METH_VARARGS},
  {"readPtr", py_readPtr, METH_VARARGS},
  {"readInt", py_readInt, METH_VARARGS},
  {"sLong", py_sLong, METH_VARARGS},
  {"le32_to_cpu", py_le32_to_cpu, METH_VARARGS},
  {"le16_to_cpu", py_le16_to_cpu, METH_VARARGS},
  {"cpu_to_le32", py_le32_to_cpu, METH_VARARGS},
  {"getListSize", py_getlistsize, METH_VARARGS},
  {"getFullBuckets", py_getFullBuckets, METH_VARARGS},
  {"getFullBucketsH", py_getFullBuckets_h, METH_VARARGS},
  {"FD_ISSET", py_FD_ISSET, METH_VARARGS},
  {"gdb_whatis", py_gdb_whatis, METH_VARARGS},
  {"gdb_typeinfo", py_gdb_typeinfo, METH_VARARGS},
  {"set_readmem_task", py_readmem_task, METH_VARARGS},
  {"get_NR_syscalls", py_get_NR_syscalls, METH_VARARGS},
  {"register_epython_prog", py_register_epython_prog, METH_VARARGS},
  {"set_default_timeout", py_set_default_timeout, METH_VARARGS},
  {"get_pathname", py_get_pathname, METH_VARARGS},
  {"setprocname", py_setprocname, METH_VARARGS},
  {"is_task_active", py_is_task_active,  METH_VARARGS},
  {"pid_to_task", py_pid_to_task,  METH_VARARGS},
  {"task_to_pid", py_task_to_pid,  METH_VARARGS},
  {"get_uptime", py_get_uptime,  METH_VARARGS},
  {"get_task_mem_usage", py_get_task_mem_usage,  METH_VARARGS},
  {NULL,      NULL}        /* Sentinel */
};

    static struct PyModuleDef crashmodule = {
        PyModuleDef_HEAD_INIT,
        "crash",		/* m_name */
        "Low-level Python API to crash internals",  /* m_doc */
        -1,			/* m_size */
        crashMethods,		/* m_methods */
        NULL,			/* m_reload */
        NULL,			/* m_traverse */
        NULL,			/* m_clear */
        NULL,			/* m_free */
    };

extern const char * crashmod_version;

PyMODINIT_FUNC PyInit_crash(void) {

  unsigned int i;
  m = PyModule_Create(&crashmodule);
  if (m == NULL)
        return NULL;

  d = PyModule_GetDict(m);
  crashError = PyErr_NewException("crash.error", NULL, NULL);
  Py_INCREF(crashError);
  PyModule_AddObject(m, "error", crashError);

  PyModule_AddObject(m, "version", PyString_FromString(crashmod_version));

  PyModule_AddObject(m, "KVADDR", PyInt_FromLong(KVADDR));
  PyModule_AddObject(m, "UVADDR", PyInt_FromLong(UVADDR));
  PyModule_AddObject(m, "PHYSADDR", PyInt_FromLong(PHYSADDR));
  PyModule_AddObject(m, "XENMACHADDR", PyInt_FromLong(XENMACHADDR));
  //PyModule_AddObject(m, "FILEADDR", PyInt_FromLong(FILEADDR));
  PyModule_AddObject(m, "AMBIGUOUS", PyInt_FromLong(AMBIGUOUS));

  PyModule_AddObject(m, "PAGESIZE", PyInt_FromLong(PAGESIZE()));
  PyModule_AddObject(m, "PAGE_CACHE_SHIFT", 
                     PyInt_FromLong(machdep->pageshift));
  PyModule_AddObject(m, "HZ", PyInt_FromLong(machdep->hz));

  PyModule_AddObject(m, "WARNING", PyString_FromString("++WARNING+++"));

  PyModule_AddObject(m, "Crash_run", PyString_FromString(build_version));
  PyModule_AddObject(m,
		     "Crash_build",PyString_FromString(build_crash_version));

  // Register GDB-internal enums
  py_gdb_register_enums(m);

  // Now create some aliases

  // Initialize size/type tables
  for (i=0; i < sizeof(functable_signed)/sizeof(conversion_func); i++) {
    functable_signed[i] = nu_badsize;
    functable_usigned[i] = nu_badsize;
  }

  functable_signed[sizeof(char)-1] = nu_byte;
  functable_signed[sizeof(short)-1] = nu_short;
  functable_signed[sizeof(int)-1] = nu_int;
  functable_signed[sizeof(long)-1] = nu_long;
  functable_signed[sizeof(long long)-1] = nu_longlong;

  functable_usigned[sizeof(char)-1] = nu_ubyte;
  functable_usigned[sizeof(short)-1] = nu_ushort;
  functable_usigned[sizeof(int)-1] = nu_uint;
  functable_usigned[sizeof(long)-1] = nu_ulong;
  functable_usigned[sizeof(long long)-1] = nu_ulonglong;

  return m;
}

