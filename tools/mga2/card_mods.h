#ifndef MGA2_CARD_MODS_H
#define MGA2_CARD_MODS_H

#include "ge_shared.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct SrMGA2CardMod SrMGA2CardMod;

const SrMGA2CardMod *sr_mga2_card_mod_find(const GeState *state);
uint32_t sr_mga2_card_mod_scale(const SrMGA2CardMod *mod);
uint64_t sr_mga2_card_mod_max_pixels(uint32_t texture_scale);
int sr_mga2_card_mod_sample(
    const SrMGA2CardMod *mod, uint32_t u, uint32_t v, uint32_t *rgba);
int sr_mga2_card_mod_mip_dimensions(
    uint32_t width, uint32_t height, uint32_t scale, uint32_t level,
    uint32_t *output_width, uint32_t *output_height);
int sr_mga2_card_mod_compose(
    const SrMGA2CardMod *mod, const uint32_t *original, uint32_t width,
    uint32_t height, uint32_t scale, uint32_t level, uint32_t output_width,
    uint32_t output_height, uint32_t *destination);
void sr_mga2_card_mod_shutdown(void);

#ifdef __cplusplus
}
#endif

#endif
