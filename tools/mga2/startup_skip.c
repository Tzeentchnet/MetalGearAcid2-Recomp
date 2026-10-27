#include "recomp.h"

#include <stdio.h>

#define TITLE_CODE_START 0x09a12658u
#define TITLE_SERVER_UPDATE 0x09a1289cu
#define TITLE_SERVER_DESTROY 0x09a1292cu
#define TITLE_SERVER_TAG 0x09a1ce40u

#define TITLE_SERVER_SCAN_START 0x08800000u
#define TITLE_SERVER_SCAN_END 0x09a00000u

#define TITLE_ACTIVE_OBJECT_OFFSET 0x10u
#define TITLE_ACTION_OFFSET 0x48u
#define TITLE_PHASE_OFFSET 0x4cu
#define TITLE_ARGUMENT_1_OFFSET 0x50u
#define TITLE_ARGUMENT_2_OFFSET 0x54u
#define TITLE_ARGUMENT_3_OFFSET 0x58u
#define TITLE_ARGUMENT_4_OFFSET 0x5cu
#define TITLE_ARGUMENT_5_OFFSET 0x60u
static uint32_t s_title_server;
static uint32_t s_last_scan_presentation;
static uint32_t s_current_presentation;
static int s_menu_queued;
static int s_finished;

static int title_overlay_matches(void) {
    return
        sr_r32(TITLE_CODE_START + 0x00u) == 0x27bdffe0u &&
        sr_r32(TITLE_CODE_START + 0x0cu) == 0x3c0409a2u &&
        sr_r32(TITLE_CODE_START + 0x10u) == 0x2484ce30u &&
        sr_r32(TITLE_SERVER_UPDATE + 0x00u) == 0x27bdfff0u &&
        sr_r32(TITLE_SERVER_TAG + 0x00u) == 0x73206974u &&
        sr_r32(TITLE_SERVER_TAG + 0x04u) == 0x65767265u &&
        sr_r32(TITLE_SERVER_TAG + 0x08u) == 0x00002072u;
}

static int user_pointer(uint32_t address) {
    return !(address & 3u) &&
        address >= TITLE_SERVER_SCAN_START &&
        address < 0x0a000000u;
}

static int title_server_matches(uint32_t address) {
    return
        user_pointer(address) &&
        user_pointer(sr_r32(address + 0x00u)) &&
        sr_r32(address + 0x04u) == TITLE_SERVER_UPDATE &&
        sr_r32(address + 0x0cu) == 1u &&
        sr_r32(address + 0x14u) == TITLE_SERVER_DESTROY &&
        sr_r32(address + 0x1cu) == 3u &&
        user_pointer(sr_r32(address + 0x20u)) &&
        sr_r32(address + 0x44u) == 2u &&
        sr_r32(address + 0x64u) == 0x59u;
}

static uint32_t find_title_server(void) {
    const uint32_t *words =
        (const uint32_t *)SR_HOST(TITLE_SERVER_SCAN_START);
    const uint32_t word_count =
        (TITLE_SERVER_SCAN_END - TITLE_SERVER_SCAN_START) /
        (uint32_t)sizeof(*words);

    for (uint32_t i = 0; i + 26u < word_count; i++) {
        if (words[i + 1u] != TITLE_SERVER_UPDATE ||
            words[i + 3u] != 1u ||
            words[i + 5u] != TITLE_SERVER_DESTROY ||
            words[i + 7u] != 3u ||
            words[i + 17u] != 2u ||
            words[i + 18u] != 0xffffffffu ||
            words[i + 19u] != 0xffffffffu ||
            words[i + 25u] != 0x59u) {
            continue;
        }

        uint32_t address =
            TITLE_SERVER_SCAN_START + i * (uint32_t)sizeof(*words);
        if (title_server_matches(address))
            return address;
    }
    return 0;
}

static void queue_menu_transition(uint32_t presentation) {
    sr_w32(s_title_server + TITLE_ACTION_OFFSET, 3u);
    sr_w32(s_title_server + TITLE_PHASE_OFFSET, 2u);
    sr_w32(s_title_server + TITLE_ARGUMENT_1_OFFSET, 0u);
    sr_w32(s_title_server + TITLE_ARGUMENT_2_OFFSET, 1u);
    sr_w32(s_title_server + TITLE_ARGUMENT_3_OFFSET, 0u);
    sr_w32(s_title_server + TITLE_ARGUMENT_4_OFFSET, 0u);
    sr_w32(s_title_server + TITLE_ARGUMENT_5_OFFSET, 0u);
    s_menu_queued = 1;
    fprintf(
        stderr,
        "startup skip: queued title-menu transition at presentation %u\n",
        presentation);
}

static void suppress_deferred_logo_transition(uint32_t presentation) {
    if (!s_menu_queued ||
        !title_server_matches(s_title_server) ||
        sr_r32(s_title_server + TITLE_ACTION_OFFSET) != 1u ||
        sr_r32(s_title_server + TITLE_PHASE_OFFSET) != 3u) {
        return;
    }

    sr_w32(s_title_server + TITLE_ACTION_OFFSET, 0xffffffffu);
    fprintf(
        stderr,
        "startup skip: suppressed deferred logo transition at "
        "presentation %u\n",
        presentation);
}

void sr_mga2_skip_startup_action_hook(CpuState *state) {
    if (!s_menu_queued || !title_overlay_matches()) return;

    uint32_t server = state->r[16];
    if (!title_server_matches(server)) return;
    s_title_server = server;

    suppress_deferred_logo_transition(s_current_presentation);
}

void sr_mga2_skip_startup_tick(uint32_t presentation) {
    s_current_presentation = presentation;
    if (s_finished) return;
    if (!title_overlay_matches()) {
        if (s_menu_queued) s_finished = 1;
        return;
    }

    if (!s_title_server) {
        if (presentation < 400u ||
            presentation - s_last_scan_presentation < 4u) {
            return;
        }
        s_last_scan_presentation = presentation;
        s_title_server = find_title_server();
        if (!s_title_server) {
            if (presentation == 800u) {
                fprintf(
                    stderr,
                    "startup skip: title server was not found by "
                    "presentation %u\n",
                    presentation);
            }
            return;
        }
    }

    if (!title_server_matches(s_title_server)) {
        if (s_menu_queued) {
            s_finished = 1;
        } else {
            s_title_server = 0;
        }
        return;
    }

    if (!s_menu_queued) {
        if (sr_r32(s_title_server + TITLE_ACTIVE_OBJECT_OFFSET) ==
                0x08a79780u &&
            sr_r32(s_title_server + TITLE_ACTION_OFFSET) == 0xffffffffu &&
            sr_r32(s_title_server + TITLE_PHASE_OFFSET) == 0xffffffffu) {
            queue_menu_transition(presentation);
        }
        return;
    }

    suppress_deferred_logo_transition(presentation);
}
