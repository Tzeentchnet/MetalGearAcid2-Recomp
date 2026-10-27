#include "graphics_config.h"
#include "graphics_settings.h"

int main(void) {
    int result;
    if (!sr_graphics_config_init()) return 2;
    result = sr_graphics_settings_show("Metal Gear Acid 2 Graphics");
    return result < 0 ? 2 : 0;
}
