#ifndef MGA2_OUTLINE_POLICY_H
#define MGA2_OUTLINE_POLICY_H

#include "ge_shared.h"

#ifdef __cplusplus
extern "C" {
#endif

int sr_mga2_outline_feedback(const GeState *state);
int sr_mga2_outline_sprite(
    const GeState *state, const GeVtx *first, const GeVtx *second,
    int perspective);

#ifdef __cplusplus
}
#endif

#endif
