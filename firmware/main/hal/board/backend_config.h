/*
 * SPDX-FileCopyrightText: 2026 M5Stack Technology CO LTD
 *
 * SPDX-License-Identifier: MIT
 */
#ifndef _STACKCHAN_BACKEND_CONFIG_H_
#define _STACKCHAN_BACKEND_CONFIG_H_

namespace hal_bridge {

// Provisions the PC-backend connection settings into NVS before the xiaozhi
// Application starts (Phase 3 / Issue #5, ADR-0004).
//
// Effect (all driven by build-time Kconfig under "StackChan Server", never
// hardcoded):
//   * When CONFIG_STACKCHAN_BACKEND_OTA_URL is non-empty, writes it to NVS
//     wifi.ota_url, replacing the cloud default (api.tenclass.net). This is the
//     intervention point that disables cloud activation: Ota::CheckVersion then
//     talks to the backend, which returns a "websocket" section (and no
//     "activation" section) so the Application selects WebsocketProtocol and
//     skips the activation-code flow.
//   * Seeds NVS websocket.url / token / version from the corresponding Kconfig
//     defaults, but only for keys that are currently empty/unset, so values
//     provisioned at runtime (Setup/BLE, TODO(issue#5-follow)) are preserved.
//
// It does NOT touch firmware/xiaozhi-esp32 and never overwrites a non-empty
// runtime value. Safe to call every boot before Application::Initialize().
void provision_backend_connection();

}  // namespace hal_bridge

#endif  // _STACKCHAN_BACKEND_CONFIG_H_
