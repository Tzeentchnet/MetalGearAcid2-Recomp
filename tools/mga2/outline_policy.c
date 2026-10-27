#include "outline_policy.h"

#include <math.h>

static int diagonal_offset(float first, float second) {
    float offset = first - second;
    return isfinite(offset) && fabsf(fabsf(offset) - 1.0f) <= 0.0625f;
}

int sr_mga2_outline_feedback(const GeState *state) {
    /* A cached snapshot is valid only when outlines cannot change its index bit. */
    return state && !state->clear && state->tex_enable && !state->tex_swizzle &&
           state->tex_fmt == 6u && (state->fbfmt & 3u) == 1u &&
           state->fbw == 512u && state->tex_bufw == 512u &&
           state->tex_w == 512 && state->tex_h == 512 &&
           (state->tex_addr & 0x0f000000u) == 0x04000000u &&
           (state->tex_addr & 0x001fffffu) ==
               (state->fbp & 0x001fffffu) &&
           ((state->clut_fmt >> 2) & 31u) == 15u &&
           ((state->clut_fmt >> 8) & 255u) == 1u &&
           (!state->stencil_test_enable ||
            (state->stencil_op & 0x00070707u) == 0u) &&
           (state->tex_filter & 0x101u) == 0u &&
           (!(state->tex_filter & 4u) || state->tex_max_level == 0);
}

int sr_mga2_outline_sprite(
    const GeState *state, const GeVtx *first, const GeVtx *second,
    int perspective) {
    float dx0;
    float dx1;
    float dy0;
    float dy1;
    if (!sr_mga2_outline_feedback(state) || !first || !second || perspective ||
        !state->atest_enable || (state->atest & 0x00ffffffu) != 0x00ff0003u ||
        !state->stencil_test_enable ||
        (state->stencil_test & 0x00ffffffu) != 0x00ff0002u ||
        (state->tex_func & 0x00010107u) != 0x00000100u ||
        state->blend_enable || state->logic_op_enable || state->mask_rgb != 0u ||
        second->r < 0 || second->r > 64 ||
        second->g < 0 || second->g > 64 ||
        second->b < 0 || second->b > 64 || second->a != 255) {
        return 0;
    }

    dx0 = first->x - first->u;
    dx1 = second->x - second->u;
    dy0 = first->y - first->v;
    dy1 = second->y - second->v;
    return diagonal_offset(first->x, first->u) &&
           diagonal_offset(first->y, first->v) &&
           isfinite(dx1) && isfinite(dy1) &&
           fabsf(dx0 - dx1) <= 0.0625f &&
           fabsf(dy0 - dy1) <= 0.0625f;
}
