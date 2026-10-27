#include "graphics_config.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

static int failures;

static void check(const char *name, int value) {
    if (!value) {
        fprintf(stderr, "FAIL: %s\n", name);
        failures++;
    }
}

int main(void) {
    SrGraphicsConfig config;
    char error[256];
    char directory[MAX_PATH];
    char path[MAX_PATH];
    DWORD length;

    sr_graphics_config_defaults(&config);
    check("original default", config.outlines == SR_GRAPHICS_OUTLINES_ORIGINAL);
    check("legacy config",
        sr_graphics_config_parse(
            &config, "renderer=vk\n", error, sizeof(error)) &&
        config.outlines == SR_GRAPHICS_OUTLINES_ORIGINAL);
    check("parse sharper",
        sr_graphics_config_parse(
            &config, "outlines=ShArPeR\n", error, sizeof(error)) &&
        config.outlines == SR_GRAPHICS_OUTLINES_SHARPER);
    check("parse off",
        sr_graphics_config_parse(
            &config, "outlines=off\n", error, sizeof(error)) &&
        config.outlines == SR_GRAPHICS_OUTLINES_OFF);
    check("reject invalid mode",
        !sr_graphics_config_parse(
            &config, "outlines=smooth\n", error, sizeof(error)) &&
        strstr(error, "expected original, sharper, or off") != NULL);
    check("reject duplicate mode",
        !sr_graphics_config_parse(
            &config, "outlines=off\noutlines=original\n",
            error, sizeof(error)) &&
        strstr(error, "duplicate setting") != NULL);

    length = GetTempPathA((DWORD)sizeof(directory), directory);
    check("temporary directory", length > 0 && length < sizeof(directory));
    if (!length || length >= sizeof(directory)) return 1;
    snprintf(path, sizeof(path), "%smga2-outline-%lu.ini",
             directory, (unsigned long)GetCurrentProcessId());
    DeleteFileA(path);
    _putenv_s("SR_GRAPHICS_CONFIG", path);
    check("initialize graphics config", sr_graphics_config_init());
    sr_graphics_config_defaults(&config);
    for (int mode = SR_GRAPHICS_OUTLINES_ORIGINAL;
         mode <= SR_GRAPHICS_OUTLINES_OFF; mode++) {
        FILE *file;
        char text[512] = {0};
        size_t used;
        SrGraphicsConfig parsed;
        config.outlines = mode;
        check("save outline mode",
              sr_graphics_config_save(&config, error, sizeof(error)));
        file = fopen(path, "rb");
        check("open saved config", file != NULL);
        if (!file) continue;
        used = fread(text, 1, sizeof(text) - 1u, file);
        check("read saved config", !ferror(file));
        check("close saved config", fclose(file) == 0);
        text[used] = 0;
        sr_graphics_config_defaults(&parsed);
        check("round-trip outline mode",
            sr_graphics_config_parse(&parsed, text, error, sizeof(error)) &&
            parsed.outlines == mode);
    }
    config.outlines = -1;
    check("reject invalid saved mode",
          !sr_graphics_config_save(&config, error, sizeof(error)));
    _putenv_s("SR_GRAPHICS_CONFIG", "");
    DeleteFileA(path);

    if (failures) return 1;
    puts("outline config tests passed");
    return 0;
}
