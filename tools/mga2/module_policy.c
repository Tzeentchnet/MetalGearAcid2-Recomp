#include "recomp.h"

#include <stddef.h>

extern const SrDispatchTable mga2_kjfs_dispatch_table;
extern const SrDispatchTable mga2_zlib_dispatch_table;
extern const SrDispatchTable mga2_sound_dispatch_table;
extern const SrDispatchTable mga2_stage_init_dispatch_table;
extern const SrDispatchTable mga2_stage_resource_dispatch_table;
extern const SrDispatchTable mga2_stage_title_dispatch_table;
extern const SrDispatchTable mga2_stage_tu0000_dispatch_table;
extern const SrDispatchTable mga2_stage_intermission_dispatch_table;
extern const SrDispatchTable mga2_stage_st0000_dispatch_table;
extern const SrDispatchTable mga2_stage_a0001_dispatch_table;

static const SrModulePolicyEntry s_mga2_modules[] = {
    {
        "disc0:/PSP_GAME/USRDIR/modules/kjfs.prx",
        "KCEJ_FS",
        "b796d866409eb591d0fe2e27f92795296c25a61e",
        SR_MODULE_GUEST,
        0x099c7b00,
        &mga2_kjfs_dispatch_table,
    },
    {
        "disc0:/PSP_GAME/USRDIR/modules/zlibdec.prx",
        "ZLIB",
        "45b48c0479eea09da73a131d6084760f23839f4c",
        SR_MODULE_GUEST,
        0x099d7f00,
        &mga2_zlib_dispatch_table,
    },
    {
        "disc0:/PSP_GAME/USRDIR/modules/sound.prx",
        "KCEJ_SOUND",
        "7b0f681aa633984654422c65c1105c1bb4851a1e",
        SR_MODULE_GUEST,
        0x099dc000,
        &mga2_sound_dispatch_table,
    },
    {
        "disc0:/sce_lbn0x6ad80_size0x8b21",
        "mgp_stage",
        "96cad7d3f6a44a074c58b879970f8f8031a4b7c8",
        SR_MODULE_GUEST,
        0x09a0b500,
        &mga2_stage_init_dispatch_table,
    },
    {
        "disc0:/sce_lbn0x67b10_size0xe67",
        "mgp_stage",
        "9ea9d8cc73f622fe7f54029d7326c65341ff05e1",
        SR_MODULE_GUEST,
        0x09a0b500,
        &mga2_stage_resource_dispatch_table,
    },
    {
        "disc0:/sce_lbn0x649f0_size0xe67",
        "mgp_stage",
        "9ea9d8cc73f622fe7f54029d7326c65341ff05e1",
        SR_MODULE_GUEST,
        0x09a0b500,
        &mga2_stage_resource_dispatch_table,
    },
    {
        "disc0:/sce_lbn0x639f0_size0x17e13",
        "mgp_stage",
        "a21def8fe88964caf4ddafeb10000301796fcc5e",
        SR_MODULE_GUEST,
        0x09a0b500,
        &mga2_stage_title_dispatch_table,
    },
    {
        "disc0:/sce_lbn0x66200_size0x1bf0f",
        "mgp_stage",
        "c57ce9a4af60ba86808d48a3cabf3a3b7b397e9e",
        SR_MODULE_GUEST,
        0x09a0b500,
        &mga2_stage_tu0000_dispatch_table,
    },
    {
        "disc0:/sce_lbn0x62240_size0x22a51",
        "mgp_stage",
        "cc53bb130dd68d55ecbd6e179e8ab5120037ba41",
        SR_MODULE_GUEST,
        0x09a0b500,
        &mga2_stage_intermission_dispatch_table,
    },
    {
        "disc0:/sce_lbn0x62d90_size0x5331",
        "mgp_stage",
        "436c19f97a9dc3858fd9c2d30010ae466e5092ba",
        SR_MODULE_GUEST,
        0x09a0b500,
        &mga2_stage_st0000_dispatch_table,
    },
    {
        "disc0:/sce_lbn0x680f0_size0x154b8",
        "mgp_stage",
        "231bd5573c63874ea2bb23dd3f9f9955238b5c4f",
        SR_MODULE_GUEST,
        0x09a0b500,
        &mga2_stage_a0001_dispatch_table,
    },
    {
        "disc0:/PSP_GAME/USRDIR/modules/videocodec.prx",
        "*",
        "ae7c1d145ed56c702dfe68f4e111fb550f75cfc5",
        SR_MODULE_HLE,
        0,
        NULL,
    },
    {
        "disc0:/PSP_GAME/USRDIR/modules/audiocodec.prx",
        "*",
        "40b9e5611b01be8db99747bcf44dd77148da9996",
        SR_MODULE_HLE,
        0,
        NULL,
    },
    {
        "disc0:/PSP_GAME/USRDIR/modules/sc_sascore.prx",
        "*",
        "2efd9667501f3914031edeee591add4c3a7590ad",
        SR_MODULE_HLE,
        0,
        NULL,
    },
    {
        "disc0:/PSP_GAME/USRDIR/modules/libatrac3plus.prx",
        "*",
        "66d98277044766190bd068a25d4ccbf73ff845f2",
        SR_MODULE_HLE,
        0,
        NULL,
    },
    {
        "disc0:/PSP_GAME/USRDIR/modules/mpegbase.prx",
        "*",
        "c5309ceaa2af26a35885687009b46a193300c384",
        SR_MODULE_HLE,
        0,
        NULL,
    },
    {
        "disc0:/PSP_GAME/USRDIR/modules/mpeg.prx",
        "*",
        "337d306adde85492affe528047e205fb4041ee14",
        SR_MODULE_HLE,
        0,
        NULL,
    },
    {
        "disc0:/sce_lbn0xb760_size0x5bc0",
        "*",
        "1b107660cd2b2c9ac946243822e67d0d421b9a91",
        SR_MODULE_HLE,
        0,
        NULL,
    },
};

void sr_mga2_register_module_policy(void) {
    sr_module_set_policy(
        s_mga2_modules,
        (uint32_t)(sizeof(s_mga2_modules) / sizeof(s_mga2_modules[0])));
}
