#include "outline_policy.h"

#include <stdio.h>
#include <string.h>

static int failures;

static void check(const char *name, int actual, int expected) {
    if (!!actual != !!expected) {
        fprintf(stderr, "FAIL: %s\n", name);
        failures++;
    }
}

int main(void) {
    GeState state;
    GeVtx first;
    GeVtx second;
    memset(&state, 0, sizeof(state));
    memset(&first, 0, sizeof(first));
    memset(&second, 0, sizeof(second));
    state.fbp = 0x04000000u;
    state.fbw = 512u;
    state.fbfmt = 1u;
    state.tex_enable = 1;
    state.tex_addr = 0x04000000u;
    state.tex_bufw = 512u;
    state.tex_fmt = 6u;
    state.tex_w = 512;
    state.tex_h = 512;
    state.tex_func = 0x100u;
    state.clut_fmt = 0x13du;
    state.stencil_test_enable = 1;
    state.stencil_test = 0xff0002u;
    state.atest_enable = 1;
    state.atest = 0x00ff0003u;
    second.u = 32.0f;
    second.v = 68.0f;
    second.r = 16;
    second.g = 11;
    second.b = 6;
    second.a = 255;

    for (int dy = -1; dy <= 1; dy += 2) {
        for (int dx = -1; dx <= 1; dx += 2) {
            first.x = (float)dx;
            first.y = (float)dy;
            second.x = 32.0f + (float)dx;
            second.y = 68.0f + (float)dy;
            check("diagonal outline", sr_mga2_outline_sprite(
                &state, &first, &second, 0), 1);
        }
    }
    state.fbp = 0x04044000u;
    state.tex_addr = 0x04044000u;
    check("alternating framebuffer", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 1);
    check("perspective sprite", sr_mga2_outline_sprite(
        &state, &first, &second, 1), 0);

    state.tex_addr += 2u;
    check("different framebuffer view", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.tex_addr -= 2u;
    state.tex_fmt = 5u;
    check("other indexed texture", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.tex_fmt = 6u;
    state.tex_swizzle = 1;
    check("swizzled feedback", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.tex_swizzle = 0;
    state.clut_fmt = 0x139u;
    check("feedback indexed by RGB", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.clut_fmt = 0x33du;
    check("feedback indexed by multiple bits", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.clut_fmt = 0x13du;
    state.stencil_op = 1u;
    check("stencil failure changes feedback", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.stencil_op = 1u << 8;
    check("depth failure changes feedback", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.stencil_op = 1u << 16;
    check("stencil pass changes feedback", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.stencil_test_enable = 0;
    check("disabled stencil preserves feedback", sr_mga2_outline_feedback(&state), 1);
    check("outline requires stencil test", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.stencil_test_enable = 1;
    state.stencil_op = 0u;
    state.stencil_test = 0x00ff0001u;
    check("other stencil test", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.stencil_test = 0x00ff0002u;
    state.tex_func = 0x101u;
    check("other texture function", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.tex_func = 0x100u;
    state.blend_enable = 1;
    check("blended feedback effect", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.blend_enable = 0;
    state.logic_op_enable = 1;
    check("logic feedback effect", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.logic_op_enable = 0;
    state.mask_rgb = 1u;
    check("masked feedback effect", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.mask_rgb = 0u;
    state.atest_enable = 0;
    check("other alpha state", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.atest_enable = 1;
    state.tex_filter = 1u;
    check("linear feedback", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.tex_filter = 4u;
    state.tex_max_level = 1;
    check("active mip filtering", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    state.tex_max_level = 0;
    check("inactive mip filtering", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 1);
    state.tex_filter = 0u;
    second.r = 28;
    second.g = 21;
    second.b = 37;
    check("tutorial purple outline", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 1);
    second.r = 65;
    check("bright feedback effect", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    second.r = 16;
    second.g = 11;
    second.b = 6;
    second.x += 1.0f;
    check("scaled feedback effect", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);
    second.x -= 1.0f;
    first.x = first.u;
    second.x = second.u;
    check("non-diagonal feedback", sr_mga2_outline_sprite(
        &state, &first, &second, 0), 0);

    if (failures) return 1;
    puts("outline policy tests passed");
    return 0;
}
