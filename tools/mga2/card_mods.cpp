#include "card_mods.h"

extern "C" {
#include "recomp.h"
#include "settings_path.h"
}

#include <windows.h>
#include <wincodec.h>

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MGA2_CARD_MAX_RECORDS 4096u
#define MGA2_CARD_MAX_SCALE 8u
#define MGA2_CARD_MAX_BYTES (512ull * 1024ull * 1024ull)

struct SrMGA2CardMod {
    char pack[3];
    uint32_t index, identifier, count, descriptors, metadata, palette_offset;
    uint32_t storage_width, storage_height, format, width, height;
    uint64_t indices_hash, palette_hash;
    uint32_t scale;
    uint32_t *pixels;
    uint32_t *native;
    bool reported;
};

struct KnownCard {
    char pack[3];
    uint32_t index, identifier;
};

static SrMGA2CardMod s_mods[MGA2_CARD_MAX_RECORDS];
static uint32_t s_mod_count;
static uint64_t s_mod_bytes;
static int s_initialized;
static int s_registered_cleanup;

static uint64_t fnv64(const uint8_t *bytes, size_t size) {
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < size; i++) {
        hash ^= bytes[i];
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

static uint32_t next_power_of_two(uint32_t value) {
    uint32_t result = 1;
    while (result < value) result <<= 1;
    return result;
}

static bool supported_pack(const char *pack) {
    return strcmp(pack, "ac") == 0 || strcmp(pack, "ch") == 0 ||
           strcmp(pack, "it") == 0 || strcmp(pack, "sp") == 0 ||
           strcmp(pack, "wp") == 0;
}

static bool parse_record(const char *line, SrMGA2CardMod *record) {
    unsigned long long indices_hash, palette_hash;
    char extra;
    memset(record, 0, sizeof(*record));
    int count = sscanf(
        line, "%2s %" SCNu32 " %" SCNx32 " %" SCNu32 " %" SCNu32
        " %" SCNu32 " %" SCNu32 " %" SCNu32 " %" SCNu32 " %" SCNu32
        " %" SCNu32 " %" SCNu32 " %llx %llx %c",
        record->pack, &record->index, &record->identifier, &record->count,
        &record->descriptors, &record->metadata, &record->palette_offset,
        &record->storage_width, &record->storage_height, &record->format,
        &record->width, &record->height, &indices_hash, &palette_hash, &extra);
    if (count != 14 || !supported_pack(record->pack) ||
        !record->count || record->count > MGA2_CARD_MAX_RECORDS ||
        record->index >= record->count ||
        !record->width || record->width > record->storage_width ||
        !record->height || record->height > record->storage_height ||
        record->storage_width > 255u || record->storage_height > 255u ||
        (record->format != 4u && record->format != 5u) ||
        record->storage_height % 8u ||
        (record->storage_width * (record->format == 4u ? 4u : 8u)) % 128u ||
        record->descriptors > 0x1000000u || record->metadata > 0x1000000u ||
        record->palette_offset > 0x1000000u) {
        return false;
    }
    record->indices_hash = (uint64_t)indices_hash;
    record->palette_hash = (uint64_t)palette_hash;
    return true;
}

static bool card_filename(
    const SrMGA2CardMod *record, char *out, size_t out_size) {
    int length = snprintf(out, out_size, "%s_%03" PRIu32 "_%08" PRIx32 ".png",
                          record->pack, record->index, record->identifier);
    return length > 0 && (size_t)length < out_size;
}

static void release_mods(void) {
    for (uint32_t i = 0; i < s_mod_count; i++) {
        free(s_mods[i].pixels);
        free(s_mods[i].native);
    }
    memset(s_mods, 0, sizeof(s_mods));
    s_mod_count = 0;
    s_mod_bytes = 0;
}

void sr_mga2_card_mod_shutdown(void) {
    release_mods();
    s_initialized = 0;
}

static bool load_png(
    IWICImagingFactory *factory, const char *path, SrMGA2CardMod *record) {
    wchar_t wide_path[1024];
    if (!MultiByteToWideChar(
            CP_ACP, MB_ERR_INVALID_CHARS, path, -1,
            wide_path, (int)(sizeof(wide_path) / sizeof(wide_path[0])))) {
        fprintf(stderr, "card mods: cannot convert PNG path %s (error %lu)\n",
                path, (unsigned long)GetLastError());
        return false;
    }
    IWICBitmapDecoder *decoder = nullptr;
    IWICBitmapFrameDecode *frame = nullptr;
    IWICFormatConverter *converter = nullptr;
    HRESULT hr = factory->CreateDecoderFromFilename(
        wide_path, nullptr, GENERIC_READ, WICDecodeMetadataCacheOnLoad, &decoder);
    if (SUCCEEDED(hr)) {
        GUID format;
        hr = decoder->GetContainerFormat(&format);
        if (SUCCEEDED(hr) && !IsEqualGUID(format, GUID_ContainerFormatPng))
            hr = WINCODEC_ERR_UNKNOWNIMAGEFORMAT;
    }
    if (SUCCEEDED(hr)) hr = decoder->GetFrame(0, &frame);
    UINT width = 0, height = 0;
    if (SUCCEEDED(hr)) hr = frame->GetSize(&width, &height);
    if (FAILED(hr)) {
        fprintf(stderr, "card mods: cannot decode PNG %s (HRESULT 0x%08lx)\n",
                path, (unsigned long)hr);
        if (frame) frame->Release();
        if (decoder) decoder->Release();
        return false;
    }
    if (!width || !height || width % record->width ||
        height % record->height ||
        width / record->width != height / record->height ||
        width / record->width > MGA2_CARD_MAX_SCALE) {
        fprintf(stderr,
                "card mods: %s is %ux%u; expected %ux%u multiplied by "
                "the same integer from 1 to %u\n",
                path, width, height, record->width, record->height,
                MGA2_CARD_MAX_SCALE);
        frame->Release();
        decoder->Release();
        return false;
    }
    uint32_t scale = width / record->width;
    uint64_t pixels = (uint64_t)width * height;
    uint64_t native_pixels = (uint64_t)record->width * record->height;
    uint64_t bytes = (pixels + native_pixels) * sizeof(uint32_t);
    if (bytes > MGA2_CARD_MAX_BYTES - s_mod_bytes ||
        pixels > UINT32_MAX / sizeof(uint32_t)) {
        fprintf(stderr, "card mods: PNG memory limit exceeded for %s\n", path);
        frame->Release();
        decoder->Release();
        return false;
    }
    uint32_t *rgba = (uint32_t *)malloc((size_t)pixels * sizeof(uint32_t));
    uint32_t *native = (uint32_t *)malloc(
        (size_t)native_pixels * sizeof(uint32_t));
    if (!rgba || !native) {
        fprintf(stderr, "card mods: cannot allocate pixels for %s\n", path);
        free(rgba);
        free(native);
        frame->Release();
        decoder->Release();
        return false;
    }
    hr = factory->CreateFormatConverter(&converter);
    if (SUCCEEDED(hr)) {
        hr = converter->Initialize(
            frame, GUID_WICPixelFormat32bppRGBA, WICBitmapDitherTypeNone,
            nullptr, 0.0, WICBitmapPaletteTypeCustom);
    }
    if (SUCCEEDED(hr)) {
        hr = converter->CopyPixels(
            nullptr, width * sizeof(uint32_t),
            (UINT)(pixels * sizeof(uint32_t)), (BYTE *)rgba);
    }
    if (converter) converter->Release();
    frame->Release();
    decoder->Release();
    if (FAILED(hr)) {
        fprintf(stderr, "card mods: cannot read pixels from %s (HRESULT 0x%08lx)\n",
                path, (unsigned long)hr);
        free(rgba);
        free(native);
        return false;
    }
    for (uint32_t y = 0; y < record->height; y++) {
        for (uint32_t x = 0; x < record->width; x++) {
            uint32_t channels[4] = {0, 0, 0, 0};
            for (uint32_t sy = 0; sy < scale; sy++) {
                for (uint32_t sx = 0; sx < scale; sx++) {
                    uint32_t color = rgba[(y * scale + sy) * width + x * scale + sx];
                    for (uint32_t c = 0; c < 4; c++)
                        channels[c] += (color >> (c * 8u)) & 0xffu;
                }
            }
            uint32_t samples = scale * scale;
            native[y * record->width + x] =
                ((channels[0] + samples / 2u) / samples) |
                (((channels[1] + samples / 2u) / samples) << 8) |
                (((channels[2] + samples / 2u) / samples) << 16) |
                (((channels[3] + samples / 2u) / samples) << 24);
        }
    }
    record->scale = scale;
    record->pixels = rgba;
    record->native = native;
    s_mod_bytes += bytes;
    return true;
}

static bool known_filename(
    const char *name, const KnownCard *known, uint32_t known_count) {
    char expected[64];
    for (uint32_t i = 0; i < known_count; i++) {
        int length = snprintf(
            expected, sizeof(expected), "%s_%03" PRIu32 "_%08" PRIx32 ".png",
            known[i].pack, known[i].index, known[i].identifier);
        if (length > 0 && (size_t)length < sizeof(expected) &&
            _stricmp(name, expected) == 0) return true;
    }
    return false;
}

static void report_unknown_pngs(
    const char *directory, const KnownCard *known, uint32_t known_count) {
    char pattern[1024];
    int length = snprintf(pattern, sizeof(pattern), "%s\\*.png", directory);
    if (length < 0 || (size_t)length >= sizeof(pattern)) {
        fprintf(stderr, "card mods: mod directory path is too long\n");
        return;
    }
    WIN32_FIND_DATAA found;
    HANDLE search = FindFirstFileA(pattern, &found);
    if (search == INVALID_HANDLE_VALUE) {
        DWORD error = GetLastError();
        if (error != ERROR_FILE_NOT_FOUND)
            fprintf(stderr, "card mods: cannot scan %s (error %lu)\n",
                    directory, (unsigned long)error);
        return;
    }
    do {
        if (!(found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) &&
            !known_filename(found.cFileName, known, known_count)) {
            fprintf(stderr, "card mods: unknown replacement PNG %s\\%s\n",
                    directory, found.cFileName);
        }
    } while (FindNextFileA(search, &found));
    DWORD error = GetLastError();
    if (error != ERROR_NO_MORE_FILES)
        fprintf(stderr, "card mods: cannot finish scanning %s (error %lu)\n",
                directory, (unsigned long)error);
    FindClose(search);
}

static void initialize(void) {
    if (s_initialized) return;
    s_initialized = 1;
    if (!s_registered_cleanup) {
        if (atexit(sr_mga2_card_mod_shutdown) != 0) {
            fprintf(stderr, "card mods: cannot register cleanup\n");
            return;
        }
        s_registered_cleanup = 1;
    }
    char directory[1024], catalog[1024], error[256];
    if (!sr_settings_path(
            "mods\\cards", directory, sizeof(directory), error, sizeof(error)) ||
        !sr_settings_path(
            "mods\\cards\\catalog.txt", catalog, sizeof(catalog),
            error, sizeof(error))) {
        fprintf(stderr, "card mods: %s\n", error);
        return;
    }
    DWORD attributes = GetFileAttributesA(directory);
    if (attributes == INVALID_FILE_ATTRIBUTES) {
        DWORD code = GetLastError();
        if (code != ERROR_FILE_NOT_FOUND && code != ERROR_PATH_NOT_FOUND)
            fprintf(stderr, "card mods: cannot access %s (error %lu)\n",
                    directory, (unsigned long)code);
        return;
    }
    if (!(attributes & FILE_ATTRIBUTE_DIRECTORY)) {
        fprintf(stderr, "card mods: %s is not a directory\n", directory);
        return;
    }
    FILE *stream = fopen(catalog, "rb");
    if (!stream) {
        fprintf(stderr, "card mods: cannot open catalog %s: %s\n",
                catalog, strerror(errno));
        return;
    }
    char line[512];
    if (!fgets(line, sizeof(line), stream) ||
        (strcmp(line, "MGA2_CARD_CATALOG 1\n") != 0 &&
         strcmp(line, "MGA2_CARD_CATALOG 1\r\n") != 0)) {
        fprintf(stderr, "card mods: invalid catalog header in %s\n", catalog);
        fclose(stream);
        return;
    }
    KnownCard *known = (KnownCard *)calloc(MGA2_CARD_MAX_RECORDS, sizeof(*known));
    if (!known) {
        fprintf(stderr, "card mods: cannot allocate catalog records\n");
        fclose(stream);
        return;
    }
    HRESULT com = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    bool uninitialize_com = SUCCEEDED(com);
    IWICImagingFactory *factory = nullptr;
    if (FAILED(com) && com != RPC_E_CHANGED_MODE) {
        fprintf(stderr, "card mods: COM initialization failed (HRESULT 0x%08lx)\n",
                (unsigned long)com);
        free(known);
        fclose(stream);
        return;
    }
    HRESULT hr = CoCreateInstance(
        CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
        IID_PPV_ARGS(&factory));
    if (FAILED(hr)) {
        fprintf(stderr, "card mods: PNG decoder initialization failed (HRESULT 0x%08lx)\n",
                (unsigned long)hr);
        if (uninitialize_com) CoUninitialize();
        free(known);
        fclose(stream);
        return;
    }
    uint32_t known_count = 0;
    uint32_t line_number = 1;
    bool bad_catalog = false;
    while (fgets(line, sizeof(line), stream)) {
        line_number++;
        SrMGA2CardMod record;
        if (!strchr(line, '\n') || !parse_record(line, &record) ||
            known_count >= MGA2_CARD_MAX_RECORDS) {
            fprintf(stderr, "card mods: invalid catalog entry at %s:%" PRIu32 "\n",
                    catalog, line_number);
            bad_catalog = true;
            break;
        }
        for (uint32_t i = 0; i < known_count; i++) {
            if (strcmp(known[i].pack, record.pack) == 0 &&
                known[i].index == record.index) {
                fprintf(stderr, "card mods: duplicate catalog entry at %s:%" PRIu32 "\n",
                        catalog, line_number);
                bad_catalog = true;
                break;
            }
        }
        if (bad_catalog) break;
        memcpy(known[known_count].pack, record.pack, sizeof(record.pack));
        known[known_count].index = record.index;
        known[known_count].identifier = record.identifier;
        known_count++;
        char name[64], path[1024];
        if (!card_filename(&record, name, sizeof(name))) {
            fprintf(stderr, "card mods: invalid replacement filename at %s:%" PRIu32 "\n",
                    catalog, line_number);
            bad_catalog = true;
            break;
        }
        int length = snprintf(path, sizeof(path), "%s\\%s", directory, name);
        if (length < 0 || (size_t)length >= sizeof(path)) {
            fprintf(stderr, "card mods: replacement path is too long: %s\n", name);
            bad_catalog = true;
            break;
        }
        DWORD file_attributes = GetFileAttributesA(path);
        if (file_attributes == INVALID_FILE_ATTRIBUTES) {
            DWORD code = GetLastError();
            if (code != ERROR_FILE_NOT_FOUND && code != ERROR_PATH_NOT_FOUND)
                fprintf(stderr, "card mods: cannot access %s (error %lu)\n",
                        path, (unsigned long)code);
            continue;
        }
        if (file_attributes & FILE_ATTRIBUTE_DIRECTORY) {
            fprintf(stderr, "card mods: replacement is a directory: %s\n", path);
            continue;
        }
        if (load_png(factory, path, &record)) {
            s_mods[s_mod_count++] = record;
            fprintf(stderr, "card mods: loaded %s (%" PRIu32 "x)\n", name, record.scale);
        }
    }
    if (ferror(stream)) {
        fprintf(stderr, "card mods: cannot read catalog %s: %s\n",
                catalog, strerror(errno));
        bad_catalog = true;
    }
    if (bad_catalog) {
        fprintf(stderr, "card mods: disabling replacements from the invalid catalog\n");
        release_mods();
    } else {
        report_unknown_pngs(directory, known, known_count);
    }
    factory->Release();
    if (uninitialize_com) CoUninitialize();
    free(known);
    fclose(stream);
}

static bool guest_ram_range(uint32_t address, uint64_t size) {
    uint32_t physical = SR_PHYS(address);
    return size && physical >= 0x08000000u &&
           (uint64_t)physical + size <= UINT64_C(0x0c000000);
}

static uint32_t guest_u32(uint32_t address) {
    uint32_t value;
    memcpy(&value, SR_HOST(address), sizeof(value));
    return value;
}

const SrMGA2CardMod *sr_mga2_card_mod_find(const GeState *state) {
    initialize();
    if (!s_mod_count || !state || !state->tex_enable || state->clear ||
        !state->tex_swizzle || (state->tex_fmt != 4u && state->tex_fmt != 5u) ||
        (state->clut_fmt & 3u) != 3u || ((state->clut_fmt >> 2) & 31u) ||
        ((state->clut_fmt >> 16) & 31u) || (state->tex_mode & 0x100u)) {
        return nullptr;
    }
    uint32_t mask = (state->clut_fmt >> 8) & 255u;
    if ((state->tex_fmt == 5u && mask != 255u) ||
        (state->tex_fmt == 4u && mask != 15u && mask != 255u))
        return nullptr;
    uint32_t palette = SR_PHYS(state->clut_addr);
    for (uint32_t i = 0; i < s_mod_count; i++) {
        SrMGA2CardMod *mod = &s_mods[i];
        if (state->tex_fmt != mod->format ||
            ge_texture_buffer_width(state->tex_fmt, state->tex_bufw) !=
                mod->storage_width ||
            state->tex_w != (int)next_power_of_two(mod->storage_width) ||
            state->tex_h != (int)next_power_of_two(mod->storage_height) ||
            palette < mod->palette_offset) continue;
        uint32_t base = palette - mod->palette_offset;
        uint64_t descriptor = (uint64_t)base + mod->descriptors + mod->index * 16u;
        uint64_t metadata = (uint64_t)base + mod->metadata + mod->index * 48u;
        uint32_t palette_bytes = mod->format == 4u ? 64u : 1024u;
        uint32_t index_bytes = mod->storage_width * mod->storage_height *
                               (mod->format == 4u ? 4u : 8u) / 8u;
        if (!guest_ram_range(base, 32u) || descriptor > UINT32_MAX ||
            metadata > UINT32_MAX ||
            !guest_ram_range((uint32_t)descriptor, 16u) ||
            !guest_ram_range((uint32_t)metadata, 48u) ||
            !guest_ram_range(palette, palette_bytes) ||
            !guest_ram_range(state->tex_addr, index_bytes)) continue;
        if ((guest_u32(base + 4u) & 0xffffu) != 0x800cu ||
            guest_u32(base + 8u) != mod->count ||
            SR_PHYS(guest_u32(base + 12u)) != base + mod->descriptors ||
            guest_u32(base + 16u) != mod->count ||
            SR_PHYS(guest_u32(base + 20u)) != base + mod->metadata ||
            (guest_u32((uint32_t)descriptor) & 0x00ff00ffu) !=
                (mod->storage_width | (mod->storage_height << 16)) ||
            guest_u32((uint32_t)descriptor + 4u) != (0x00020000u | mod->format) ||
            SR_PHYS(guest_u32((uint32_t)descriptor + 12u)) != palette ||
            guest_u32((uint32_t)metadata + 4u) != mod->identifier ||
            guest_u32((uint32_t)metadata + 12u) !=
                (mod->width | (mod->height << 16))) continue;
        const uint8_t *colors = (const uint8_t *)SR_HOST(palette);
        if (memcmp(colors, state->clutram, palette_bytes) != 0 ||
            fnv64(colors, palette_bytes) != mod->palette_hash) continue;
        const uint8_t *indices = (const uint8_t *)SR_HOST(state->tex_addr);
        if (fnv64(indices, index_bytes) != mod->indices_hash) continue;
        if (!mod->reported) {
            char name[64];
            if (card_filename(mod, name, sizeof(name)))
                fprintf(stderr, "card mods: applying %s\n", name);
            mod->reported = true;
        }
        return mod;
    }
    return nullptr;
}

uint32_t sr_mga2_card_mod_scale(const SrMGA2CardMod *mod) {
    return mod ? mod->scale : 1u;
}

uint64_t sr_mga2_card_mod_max_pixels(uint32_t texture_scale) {
    initialize();
    uint64_t maximum = 0;
    for (uint32_t i = 0; i < s_mod_count; i++) {
        const SrMGA2CardMod *mod = &s_mods[i];
        uint32_t scale = mod->scale > texture_scale ? mod->scale : texture_scale;
        uint64_t pixels = (uint64_t)next_power_of_two(mod->storage_width) *
                          next_power_of_two(mod->storage_height) * scale * scale;
        if (pixels > maximum) maximum = pixels;
    }
    return maximum;
}

int sr_mga2_card_mod_sample(
    const SrMGA2CardMod *mod, uint32_t u, uint32_t v, uint32_t *rgba) {
    if (!mod || !rgba || u >= mod->width || v >= mod->height) return 0;
    *rgba = mod->native[v * mod->width + u];
    return 1;
}

int sr_mga2_card_mod_mip_dimensions(
    uint32_t width, uint32_t height, uint32_t scale, uint32_t level,
    uint32_t *output_width, uint32_t *output_height) {
    if (!width || width > 512u || !height || height > 512u || !scale ||
        scale > MGA2_CARD_MAX_SCALE || level >= 16u ||
        !output_width || !output_height) return 0;
    *output_width = (width * scale) >> level;
    *output_height = (height * scale) >> level;
    if (!*output_width) *output_width = 1u;
    if (!*output_height) *output_height = 1u;
    return 1;
}

int sr_mga2_card_mod_compose(
    const SrMGA2CardMod *mod, const uint32_t *original, uint32_t width,
    uint32_t height, uint32_t scale, uint32_t level, uint32_t output_width,
    uint32_t output_height, uint32_t *destination) {
    if (!mod || !original || !destination || !width || !height ||
        width > 512u || height > 512u || !scale ||
        scale > MGA2_CARD_MAX_SCALE || level >= 16u ||
        !output_width || output_width > width * scale ||
        !output_height || output_height > height * scale ||
        (original == destination &&
         (output_width != width || output_height != height))) return 0;
    for (uint32_t y = 0; y < output_height; y++) {
        uint32_t source_y = (uint32_t)((uint64_t)y * height / output_height);
        for (uint32_t x = 0; x < output_width; x++) {
            uint32_t source_x = (uint32_t)((uint64_t)x * width / output_width);
            destination[(size_t)y * output_width + x] =
                original[(size_t)source_y * width + source_x];
        }
    }
    uint32_t divisor = 1u << level;
    uint32_t art_width = (mod->width * scale + divisor - 1u) / divisor;
    uint32_t art_height = (mod->height * scale + divisor - 1u) / divisor;
    if (!level && (art_width > output_width || art_height > output_height))
        return 0;
    if (art_width > output_width) art_width = output_width;
    if (art_height > output_height) art_height = output_height;
    uint32_t source_width = mod->width * mod->scale;
    uint32_t source_height = mod->height * mod->scale;
    for (uint32_t y = 0; y < art_height; y++) {
        uint32_t source_y = (uint32_t)((uint64_t)y * source_height / art_height);
        for (uint32_t x = 0; x < art_width; x++) {
            uint32_t source_x = (uint32_t)((uint64_t)x * source_width / art_width);
            destination[(size_t)y * output_width + x] =
                mod->pixels[(size_t)source_y * source_width + source_x];
        }
    }
    return 1;
}
