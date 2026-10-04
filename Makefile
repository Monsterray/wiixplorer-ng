# Current devkitPPC/libogc build. Keep project paths relative: checkouts may contain spaces.
.DEFAULT_GOAL := all
DEVKITPRO ?= /opt/devkitpro
DEVKITPPC ?= $(DEVKITPRO)/devkitPPC
include $(DEVKITPPC)/wii_rules

FTP_BACKEND ?= ftpsrv
CONFIG ?= release
PROBE_LEVEL ?= 1
PROBE_GROUPS ?= cpu,gpu,threads,io,network
BUILD := build/$(CONFIG)
OUTPUT := $(BUILD)/boot
PROBE_CONFIG := $(BUILD)/probe-config.h
RESOURCE_HEADER := $(BUILD)/Memory/filelist.h
PREFIX_LOCAL := .deps/prefix
SOURCES := $(shell find source -type f \( -name '*.c' -o -name '*.cpp' -o -name '*.s' -o -name '*.S' \) | LC_ALL=C sort)
SOURCES := $(filter-out source/gitrev.c,$(SOURCES)) source/gitrev.c
ifeq ($(FTP_BACKEND),ftpsrv)
SOURCES := $(filter-out source/FTPOperations/ftpii/% source/FTPOperations/MountVirtualDevices.cpp,$(SOURCES))
FTP_BACKEND_DEFINE := -DWX_FTP_LEGACY=0
else ifeq ($(FTP_BACKEND),ftpii)
SOURCES := $(filter-out source/FTPOperations/ftpsrv/% source/FTPOperations/WiiXplorerFtpVfs.cpp,$(SOURCES))
FTP_BACKEND_DEFINE := -DWX_FTP_LEGACY=1
else
$(error FTP_BACKEND must be ftpsrv or ftpii)
endif
OBJECTS := $(addprefix $(BUILD)/,$(addsuffix .o,$(SOURCES)))
ASSETS := $(wildcard data/fonts/* data/images/* data/sounds/* data/binary/*.bin)
ASSET_OBJECTS := $(addprefix $(BUILD)/,$(addsuffix .o,$(ASSETS)))
CPPFLAGS := $(FTP_BACKEND_DEFINE) -D_GNU_SOURCE -include sys/param.h -include $(PROBE_CONFIG) -I$(BUILD) -Isource -I$(PREFIX_LOCAL)/include -I$(LIBOGC_INC) \
            $(foreach dir,$(PORTLIBS),-I$(dir)/include -I$(dir)/include/freetype2) \
            -DHAVE_LIBZ -DHAVE_LIBPNG -DHAVE_LIBJPEG -DHAVE_LIBTIFF
HOST_CC ?= cc
HOST_CXX ?= c++
ifeq ($(CONFIG),debug)
OPT ?= -Og
DEBUG_FLAGS := -g3
else
OPT ?= -O2
DEBUG_FLAGS := -g
endif
CFLAGS := $(MACHDEP) -std=gnu99 $(OPT) $(DEBUG_FLAGS) -Wall -Wextra -Wno-multichar
CXXFLAGS := $(MACHDEP) -std=gnu++11 $(OPT) $(DEBUG_FLAGS) -Wall -Wextra -Wno-multichar
LDFLAGS := $(MACHDEP) -g -Wl,-Map,$(OUTPUT).map \
           -Wl,-wrap,malloc,-wrap,free,-wrap,memalign,-wrap,calloc,-wrap,realloc,-wrap,malloc_usable_size
LIBPATHS := -L$(PREFIX_LOCAL)/lib $(foreach dir,$(PORTLIBS),-L$(dir)/lib) -L$(LIBOGC_LIB)
LIBS := -Wl,--start-group -lhbcagent -lmupdf -lzip -lunrar -lsevenzip -ldi -lgd -ltiff \
        -ljpeg -lpng -lz -lfat -lext2fs -lntfs -lnfs -ltinysmb -lwiikeyboard \
        -lmad -lwiiuse -lbte -lasnd -logc -lvorbisidec -logg -lfreetype -lmxml \
        -lbrotlidec -lbrotlicommon -lbz2 -lm -Wl,--end-group

.PHONY: all generated deps clean check debug release run lang FORCE
all: $(OUTPUT).dol

$(PROBE_CONFIG): FORCE
	@python3 scripts/probe-config.py "$@" "$(CONFIG)" "$(PROBE_LEVEL)" "$(PROBE_GROUPS)" "$(OPT)" "$(CC)" "$(CFLAGS)" "$(CXXFLAGS)" "$(CPPFLAGS)"

deps:
	python3 scripts/build-deps.py
	python3 scripts/build-hbc-agent.py

$(PREFIX_LOCAL)/lib/libhbcagent.a: scripts/build-hbc-agent.py scripts/patches/hbc-agent.patch source/FileOperations/TransferFile.h source/network/TransferSocket.h
	python3 scripts/build-hbc-agent.py

generated:
	@sh gitrev.sh


$(RESOURCE_HEADER): FORCE scripts/resource-list.py $(ASSETS)
	@python3 scripts/resource-list.py "$@"

$(OBJECTS): $(PROBE_CONFIG) | generated $(RESOURCE_HEADER) $(PREFIX_LOCAL)/lib/libhbcagent.a

$(BUILD)/source/Diagnostics/MemoryBench.cpp.o: CXXFLAGS += -O2

$(BUILD)/%.cpp.o: %.cpp
	@mkdir -p "$(@D)"
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c "$<" -o "$@"
$(BUILD)/%.c.o: %.c
	@mkdir -p "$(@D)"
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c "$<" -o "$@"
$(BUILD)/%.s.o: %.s
	@mkdir -p "$(@D)"
	$(CC) $(CPPFLAGS) $(MACHDEP) -c "$<" -o "$@"
$(BUILD)/%.S.o: %.S
	@mkdir -p "$(@D)"
	$(CC) $(CPPFLAGS) $(MACHDEP) -c "$<" -o "$@"
$(BUILD)/data/%.o: data/%
	@mkdir -p "$(@D)"
	bin2s -a 32 "$<" | $(AS) -o "$@"

source/gitrev.c: | generated
	@test -f "$@"

$(OUTPUT).elf: $(OBJECTS) $(ASSET_OBJECTS) data/binary/magic_patcher.o $(PREFIX_LOCAL)/lib/libhbcagent.a $(wildcard $(PREFIX_LOCAL)/lib/*.a) Makefile
	$(CXX) $(OBJECTS) $(ASSET_OBJECTS) data/binary/magic_patcher.o $(LDFLAGS) $(LIBPATHS) $(LIBS) -o "$@"

# wii_rules supplies the ELF-to-DOL conversion.
$(OUTPUT).dol: $(OUTPUT).elf

debug release:
	$(MAKE) CONFIG=$@ all
check:
	CXX="$(HOST_CXX)" python3 tests/memory_allocator.py
	CXX="$(HOST_CXX)" python3 tests/archives.py
	CXX="$(HOST_CXX)" python3 tests/archive_fs.py
	CC="$(HOST_CC)" CXX="$(HOST_CXX)" python3 tests/archive_codecs.py
	CC="$(HOST_CC)" CXX="$(HOST_CXX)" python3 tests/native_archive_bench.py
	CC="$(HOST_CC)" CXX="$(HOST_CXX)" python3 tests/archive_seven_codec.py
	CXX="$(HOST_CXX)" python3 tests/archive_rar_codec.py
	CC="$(HOST_CC)" CXX="$(HOST_CXX)" python3 tests/regression.py
	CC="$(HOST_CC)" CXX="$(HOST_CXX)" python3 tests/stability.py
	python3 tests/dolphin_process.py
	python3 tests/dolphin_smoke.py
	CXX="$(HOST_CXX)" python3 tests/debug_launch.py
	CXX="$(HOST_CXX)" python3 tests/probes.py
	CXX="$(HOST_CXX)" python3 tests/hbc_agent.py
	CC="$(HOST_CC)" CXX="$(HOST_CXX)" python3 tests/hbc_overlay_keys.py
	CXX="$(HOST_CXX)" python3 tests/hbc_socket_mode.py
	python3 tests/hbc_smoke.py
	CXX="$(HOST_CXX)" python3 tests/storage_bench.py
	CXX="$(HOST_CXX)" python3 tests/memory_bench.py
	CXX="$(HOST_CXX)" python3 tests/transfer_socket.py
	CXX="$(HOST_CXX)" python3 tests/ftp_transfer.py
	CXX="$(HOST_CXX)" python3 tests/ftp_peers.py
	CXX="$(HOST_CXX)" python3 tests/ftp_metadata.py
	CXX="$(HOST_CXX)" python3 tests/nfs_transfer.py
	CXX="$(HOST_CXX)" python3 tests/thread_start.py
	CXX="$(HOST_CXX)" python3 tests/transfer_plan.py
	CXX="$(HOST_CXX)" python3 tests/empty_directory_transfer.py
	CXX="$(HOST_CXX)" python3 tests/ftpsrv_socket.py
	CC="$(HOST_CC)" CXX="$(HOST_CXX)" python3 tests/ftpsrv_integration.py
clean:
	rm -rf build/debug build/release boot.elf boot.dol boot.map
run: all
	bash scripts/dolphin.sh --build $(CONFIG)
lang:
	xgettext -C -cTRANSLATORS --from-code=utf-8 --sort-output --no-wrap --no-location -ktr -o Languages/boot.pot $(filter %.c %.cpp,$(SOURCES))

-include $(OBJECTS:.o=.d)
