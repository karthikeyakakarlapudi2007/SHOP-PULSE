/**
 * @file deviceHealthMonitor.ts
 * @description Automated IoT health monitoring, online/offline inspection, and alert deduplication.
 */

import { createAlert, getAlerts } from './alertService';

class DeviceHealthMonitor {
  public async inspectDevice(device: {
    id: string;
    deviceName?: string;
    isConnected?: boolean;
    batteryLevel?: number;
    signalStrength?: number;
  }): Promise<void> {
    const existingAlerts = await getAlerts({ limit: 100 });

    // 1. Offline Device Detection
    if (device.isConnected === false) {
      const hasOfflineAlert = existingAlerts.some(
        (a) => a.deviceId === device.id && a.type === 'DEVICE_OFFLINE'
      );
      if (!hasOfflineAlert) {
        await createAlert({
          type: 'DEVICE_OFFLINE',
          title: `Device Offline: ${device.deviceName || device.id}`,
          message: `Device ${device.deviceName || device.id} went offline. Check power or connection.`,
          priority: 'high',
          deviceId: device.id,
          category: 'system',
        });
      }
    }

    // 2. Low Battery Detection (< 20%)
    if (device.batteryLevel !== undefined && device.batteryLevel < 20) {
      const hasLowBatAlert = existingAlerts.some(
        (a) => a.deviceId === device.id && a.type === 'DEVICE_BATTERY_LOW'
      );
      if (!hasLowBatAlert) {
        await createAlert({
          type: 'DEVICE_BATTERY_LOW',
          title: `Low Battery: ${device.deviceName || device.id}`,
          message: `Device ${device.deviceName || device.id} battery is critically low (${device.batteryLevel}%). Recharge soon.`,
          priority: 'high',
          deviceId: device.id,
          category: 'system',
        });
      }
    }
  }
}

export const deviceHealthMonitor = new DeviceHealthMonitor();

