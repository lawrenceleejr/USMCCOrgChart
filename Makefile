PYTHON ?= python3

.PHONY: all chart fonts clean
all: fonts chart

fonts: fonts/Lato-Regular.ttf

fonts/Lato-Regular.ttf:
	./scripts/fetch-fonts.sh

chart:
	$(PYTHON) -m orgchart

clean:
	rm -f out/*.svg out/*.png
