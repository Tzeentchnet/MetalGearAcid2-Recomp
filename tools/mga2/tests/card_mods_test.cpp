#include "card_mods.h"

extern "C" {
#include "recomp.h"
}

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern "C" {
uint8_t *g_mem;
uint8_t g_scratchpad[SR_SCRATCHPAD_SIZE];
int g_sr_gpu_vram_read_watch;
int g_sr_gpu_vram_write_watch;
void sr_gpu_vram_read(uint32_t, uint32_t) {}
void sr_gpu_vram_dirty(uint32_t, uint32_t) {}
void sr_gpu_vram_prepare_write(uint32_t, uint32_t) {}
}

static void require(bool condition, const char *message) {
    if (!condition) {
        fprintf(stderr, "card mod test failed: %s\n", message);
        exit(1);
    }
}

static uint32_t read32(const uint8_t *bytes) {
    uint32_t value;
    memcpy(&value, bytes, sizeof(value));
    return value;
}

static void write32(uint8_t *bytes, uint32_t value) {
    memcpy(bytes, &value, sizeof(value));
}

static void select_palette(
    GeState *state, uint8_t *pack, uint32_t index, size_t palette_bytes) {
    uint32_t palette = read32(pack + 32u + index * 16u + 12u);
    state->clut_addr = palette;
    memset(state->clutram, 0, sizeof(state->clutram));
    memcpy(state->clutram, SR_HOST(palette), palette_bytes);
}

int main(int argc, char **argv) {
    require(argc >= 3, "expected mode and settings directory");
    require(_putenv_s("SR_SETTINGS_DIR", argv[2]) == 0, "set settings directory");
    if (strcmp(argv[1], "empty") == 0) {
        require(sr_mga2_card_mod_max_pixels(1u) == 0u, "expected no replacements");
        sr_mga2_card_mod_shutdown();
        return 0;
    }
    if (strcmp(argv[1], "limits") == 0) {
        require(sr_mga2_card_mod_max_pixels(1u) == 8192u, "accept 8x replacements");
        sr_mga2_card_mod_shutdown();
        return 0;
    }
    require(strcmp(argv[1], "valid") == 0 && argc == 5, "expected pack paths");
    g_mem = (uint8_t *)calloc(1, 0x04000000u);
    require(g_mem != nullptr, "allocate guest RAM");
    const uint32_t base = 0x08010000u;
    const uint32_t texture = 0x08020000u;
    uint8_t *pack = SR_HOST(base);
    FILE *stream = fopen(argv[3], "rb");
    require(stream != nullptr, "open synthetic pack");
    size_t size = fread(pack, 1, 0x10000u, stream);
    require(!ferror(stream) && size > 160u && size < 0x10000u, "read synthetic pack");
    fclose(stream);
    write32(pack + 4, read32(pack + 4) | 0x8000u);
    write32(pack + 12, base + read32(pack + 12));
    write32(pack + 20, base + read32(pack + 20));
    for (uint32_t i = 0; i < 2; i++) {
        uint8_t *descriptor = pack + 32u + i * 16u;
        write32(descriptor + 12, base + read32(descriptor + 12));
    }
    for (uint32_t i = 0; i < 128u; i++)
        SR_HOST(texture)[i] = (uint8_t)i;
    GeState state = {};
    state.tex_enable = 1;
    state.tex_swizzle = 1;
    state.tex_addr = texture;
    state.tex_bufw = 16;
    state.tex_fmt = 5;
    state.tex_w = 16;
    state.tex_h = 8;
    state.clut_fmt = 0xff03;
    select_palette(&state, pack, 0, 1024u);
    const SrMGA2CardMod *first = sr_mga2_card_mod_find(&state);
    require(first != nullptr, "match first resource");
    require(sr_mga2_card_mod_scale(first) == 2u, "read high-resolution scale");
    require(sr_mga2_card_mod_max_pixels(1u) == 512u, "size transfer for card scale");
    require(sr_mga2_card_mod_max_pixels(3u) == 2304u, "respect global texture scale");
    uint32_t rgba = 0;
    require(sr_mga2_card_mod_sample(first, 0u, 0u, &rgba) &&
            rgba == 0xa0192313u, "downsample RGBA for software rendering");
    require(!sr_mga2_card_mod_sample(first, 3u, 0u, &rgba), "preserve art bounds");

    uint32_t original[16 * 8];
    uint32_t composed[32 * 16];
    for (uint32_t i = 0; i < 16u * 8u; i++) original[i] = 0x7f112233u;
    require(sr_mga2_card_mod_compose(
        first, original, 16u, 8u, 2u, 0u, 32u, 16u, composed),
        "compose high-resolution art");
    require(composed[0] == 0xff000000u && composed[1] == 0x40190025u,
            "retain high-resolution detail and alpha");
    require(composed[6] == 0x7f112233u && composed[4u * 32u] == 0x7f112233u,
            "retain texture padding and logical placement");
    require(sr_mga2_card_mod_compose(
        first, original, 8u, 4u, 2u, 1u, 16u, 8u, composed),
        "compose mip level");
    require(composed[3] == 0x7f112233u && composed[2u * 16u] == 0x7f112233u,
            "mip replacement remains within the art bounds");
    require(!sr_mga2_card_mod_compose(
        first, original, 16u, 8u, 0u, 0u, 16u, 8u, composed), "reject zero scale");
    require(!sr_mga2_card_mod_compose(
        first, original, 16u, 8u, 2u, 0u, 32u, 16u, original),
        "reject aliased scaling");
    uint32_t mip_width = 0, mip_height = 0;
    require(sr_mga2_card_mod_mip_dimensions(
        16u, 8u, 2u, 4u, &mip_width, &mip_height) &&
        mip_width == 2u && mip_height == 1u,
        "calculate clamped non-square physical mip dimensions");
    require(sr_mga2_card_mod_compose(
        first, original, 1u, 1u, 2u, 4u, mip_width, mip_height, composed),
        "compose a non-square physical mip");
    require(composed[1] == 0x7f112233u, "preserve non-square mip padding");
    require(sr_mga2_card_mod_mip_dimensions(
        4u, 4u, 3u, 3u, &mip_width, &mip_height) &&
        mip_width == 1u && mip_height == 1u,
        "calculate odd-scale physical mip dimensions");
    require(sr_mga2_card_mod_compose(
        first, original, 1u, 1u, 3u, 3u, mip_width, mip_height, composed),
        "clip artwork to the physical mip extent");

    SR_HOST(texture)[0] ^= 1u;
    require(!sr_mga2_card_mod_find(&state), "reject changed texture indices");
    SR_HOST(texture)[0] ^= 1u;
    state.clutram[0] ^= 1u;
    require(!sr_mga2_card_mod_find(&state), "reject changed CLUT");
    state.clutram[0] ^= 1u;
    state.tex_w = 32;
    require(!sr_mga2_card_mod_find(&state), "reject different logical geometry");
    state.tex_w = 16;
    write32(pack + 64u + 4u, 0x999999u);
    require(!sr_mga2_card_mod_find(&state), "reject mismatched resource metadata");
    write32(pack + 64u + 4u, 0x123400u);

    select_palette(&state, pack, 1, 1024u);
    const SrMGA2CardMod *second = sr_mga2_card_mod_find(&state);
    require(second && second != first, "distinguish identical textures by resource");
    require(sr_mga2_card_mod_scale(second) == 1u, "read native replacement scale");
    require(sr_mga2_card_mod_sample(second, 2u, 1u, &rgba) &&
            rgba == 0x80ff0000u, "preserve second resource and alpha");
    require(sr_mga2_card_mod_compose(
        second, original, 16u, 8u, 1u, 0u, 16u, 8u, original),
        "compose in place at 1x");
    require(original[0] == 0x80ff0000u && original[3] == 0x7f112233u,
            "native replacement leaves padding intact");

    const uint32_t second_base = 0x08012000u;
    const uint32_t second_texture = 0x08021000u;
    uint8_t *second_pack = SR_HOST(second_base);
    stream = fopen(argv[4], "rb");
    require(stream != nullptr, "open synthetic 4-bit pack");
    size = fread(second_pack, 1, 0xe000u, stream);
    require(!ferror(stream) && size > 160u && size < 0xe000u, "read 4-bit pack");
    fclose(stream);
    write32(second_pack + 4, read32(second_pack + 4) | 0x8000u);
    write32(second_pack + 12, second_base + read32(second_pack + 12));
    write32(second_pack + 20, second_base + read32(second_pack + 20));
    for (uint32_t i = 0; i < 2; i++) {
        uint8_t *descriptor = second_pack + 32u + i * 16u;
        write32(descriptor + 12, second_base + read32(descriptor + 12));
    }
    for (uint32_t i = 0; i < 128u; i++)
        SR_HOST(second_texture)[i] = (uint8_t)i;
    state.tex_addr = second_texture;
    state.tex_bufw = 32;
    state.tex_fmt = 4;
    state.tex_w = 32;
    state.clut_fmt = 0x0f03;
    select_palette(&state, second_pack, 0, 64u);
    const SrMGA2CardMod *four_bit = sr_mga2_card_mod_find(&state);
    require(four_bit != nullptr, "match 4-bit resource");
    require(sr_mga2_card_mod_sample(four_bit, 1u, 1u, &rgba) &&
            rgba == 0x4000ff00u, "preserve 4-bit replacement and alpha");
    sr_mga2_card_mod_shutdown();
    free(g_mem);
    g_mem = nullptr;
    puts("card mod native tests passed");
    return 0;
}
