/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#include "backend_config.h"

#include <sdkconfig.h>
#include <esp_log.h>
#include <settings.h>

#include <string>
#include <string_view>

// Build-time defaults (Kconfig, "StackChan Server" menu). Absent symbols fall
// back to empty/zero so the module is a no-op unless explicitly configured.
#ifndef CONFIG_STACKCHAN_BACKEND_OTA_URL
#define CONFIG_STACKCHAN_BACKEND_OTA_URL ""
#endif
#ifndef CONFIG_STACKCHAN_BACKEND_WS_URL
#define CONFIG_STACKCHAN_BACKEND_WS_URL ""
#endif
#ifndef CONFIG_STACKCHAN_BACKEND_WS_TOKEN
#define CONFIG_STACKCHAN_BACKEND_WS_TOKEN ""
#endif
#ifndef CONFIG_STACKCHAN_BACKEND_WS_VERSION
#define CONFIG_STACKCHAN_BACKEND_WS_VERSION 0
#endif

namespace hal_bridge {

namespace {

constexpr const char* kTag = "BACKEND_CFG";

// NVS namespaces / keys read by the xiaozhi Application (do not change names):
// - Ota::GetCheckVersionUrl(): Settings("wifi").GetString("ota_url")
// - WebsocketProtocol::OpenAudioChannel(): Settings("websocket") url/token/version
constexpr const char* kWifiNamespace       = "wifi";
constexpr const char* kWifiOtaUrlKey       = "ota_url";
constexpr const char* kWebsocketNamespace  = "websocket";
constexpr const char* kWebsocketUrlKey     = "url";
constexpr const char* kWebsocketTokenKey   = "token";
constexpr const char* kWebsocketVersionKey = "version";

// Writes value only when the current stored value differs, to avoid needless
// NVS wear.
void set_string_if_changed(Settings& settings, const char* key, const std::string& value)
{
    if (settings.GetString(key) != value) {
        settings.SetString(key, value);
    }
}

}  // namespace

void provision_backend_connection()
{
    const std::string_view backend_ota_url  = CONFIG_STACKCHAN_BACKEND_OTA_URL;
    const std::string_view backend_ws_url   = CONFIG_STACKCHAN_BACKEND_WS_URL;
    const std::string_view backend_ws_token = CONFIG_STACKCHAN_BACKEND_WS_TOKEN;
    const int backend_ws_version            = CONFIG_STACKCHAN_BACKEND_WS_VERSION;

    // 1) Repoint the OTA/provisioning URL to the backend (disables the cloud
    //    activation path at api.tenclass.net). Done unconditionally when set so
    //    a stale cloud URL persisted in NVS is corrected on every boot.
    if (!backend_ota_url.empty()) {
        Settings settings(kWifiNamespace, true);
        set_string_if_changed(settings, kWifiOtaUrlKey, std::string(backend_ota_url));
        ESP_LOGI(kTag, "OTA URL pointed at backend: %s", std::string(backend_ota_url).c_str());
    } else {
        ESP_LOGW(kTag,
                 "CONFIG_STACKCHAN_BACKEND_OTA_URL is empty; cloud OTA/activation "
                 "path unchanged (see docs/backend-protocol.md §5.2)");
    }

    // 2) Seed the WebSocket connection target, but never clobber a value that
    //    was provisioned at runtime (Setup/BLE). Only fill empty/unset keys.
    Settings ws(kWebsocketNamespace, true);

    if (!backend_ws_url.empty() && ws.GetString(kWebsocketUrlKey).empty()) {
        ws.SetString(kWebsocketUrlKey, std::string(backend_ws_url));
        ESP_LOGI(kTag, "Seeded websocket.url default");
    }
    if (!backend_ws_token.empty() && ws.GetString(kWebsocketTokenKey).empty()) {
        ws.SetString(kWebsocketTokenKey, std::string(backend_ws_token));
        ESP_LOGI(kTag, "Seeded websocket.token default");
    }
    if (backend_ws_version != 0 && ws.GetInt(kWebsocketVersionKey) == 0) {
        ws.SetInt(kWebsocketVersionKey, backend_ws_version);
        ESP_LOGI(kTag, "Seeded websocket.version default: %d", backend_ws_version);
    }
}

}  // namespace hal_bridge
