PYTHON ?= python3
SCALE  ?= 2

.PHONY: all chart check fonts headshots clean
all: fonts chart

fonts: fonts/Lato-Regular.ttf

fonts/Lato-Regular.ttf:
	./scripts/fetch-fonts.sh

chart:
	$(PYTHON) -m orgchart --scale $(SCALE)

# layout clearance audit only, no output written
check:
	$(PYTHON) -m orgchart --check-only

# extract headshots from a reference render: make headshots SOURCE=chart.png
headshots:
	./scripts/extract-headshots.py $(SOURCE)

clean:
	rm -f out/*.svg out/*.png out/*.webp
