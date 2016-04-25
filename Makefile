TARGETS = . sysfs shell

all: pep8 flake8

pep8:
	pep8 -v $(TARGETS)

flake8:
	flake8 --ignore=F403 $(TARGETS)
