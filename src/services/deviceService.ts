/**
 * @file deviceService.ts
 * @description Connected device registration and telemetry tracking service using shared helpers.
 * Belongs in `src/services/deviceService.ts`.
 */

import { where } from 'firebase/firestore';
import { 
  getCollection, 
  addDocument, 
  updateDocument 
} from './firestoreHelpers';
import type { Device, RegisterDeviceInput, DeviceStatus } from '../types/device';
import { getFirebaseErrorMessage } from '../utils/firebaseErrorMapper';

const DEVICES_COLLECTION = 'devices';

/**
 * Fetch all registered hardware/mobile devices for a shop.
 */
export async function getShopDevices(shopId: string = 'default'): Promise<Device[]> {
  try {
    return await getCollection<Omit<Device, 'id'>>(DEVICES_COLLECTION, [
      where('shopId', '==', shopId)
    ]);
  } catch (err) {
    console.warn('Error fetching shop devices:', getFirebaseErrorMessage(err));
    return [];
  }
}

/**
 * Register a new device (mobile app, barcode scanner, POS terminal).
 */
export async function registerDevice(shopId: string, input: RegisterDeviceInput): Promise<Device> {
  try {
    const now = new Date().toISOString();
    const deviceData: Omit<Device, 'id'> = {
      shopId,
      name: input.name,
      type: input.type,
      status: 'active',
      lastActive: now,
      registeredAt: now,
      appVersion: input.appVersion || '1.0.0'
    };

    return await addDocument<Omit<Device, 'id'>>(DEVICES_COLLECTION, deviceData);
  } catch (err) {
    throw new Error(getFirebaseErrorMessage(err));
  }
}

/**
 * Update the active status of a device.
 */
export async function updateDeviceStatus(deviceId: string, status: DeviceStatus): Promise<void> {
  try {
    await updateDocument(DEVICES_COLLECTION, deviceId, {
      status,
      lastActive: new Date().toISOString()
    });
  } catch (err) {
    throw new Error(getFirebaseErrorMessage(err));
  }
}

export interface PairedDevice {
  id: string;
  deviceName: string;
  deviceType: string;
  connectionType: string;
  firmwareVersion?: string;
  batteryLevel?: number;
  signalStrength?: number;
  simulatorMode?: boolean;
  isConnected: boolean;
  lastSeen?: string;
  registeredAt?: string;
}

export interface DeviceTelemetry {
  batteryLevel?: number;
  signalStrength?: number;
}

export interface DeviceEvent {
  id: string;
  deviceId: string;
  eventType: string;
  payload?: any;
  timestamp: string;
}

const inMemoryPairedDevices = new Map<string, PairedDevice>();
const inMemoryDeviceEvents: DeviceEvent[] = [];

/**
 * Pair a new hardware device or smart counter.
 */
export async function pairDevice(input: {
  id?: string;
  deviceName: string;
  deviceType: string;
  connectionType: string;
  firmwareVersion?: string;
  batteryLevel?: number;
  signalStrength?: number;
  simulatorMode?: boolean;
}): Promise<PairedDevice> {
  const id = input.id || `esp32_${Math.random().toString(36).substring(2, 9)}`;
  const now = new Date().toISOString();
  const paired: PairedDevice = {
    id,
    deviceName: input.deviceName,
    deviceType: input.deviceType,
    connectionType: input.connectionType,
    firmwareVersion: input.firmwareVersion || '1.0.0',
    batteryLevel: input.batteryLevel ?? 100,
    signalStrength: input.signalStrength ?? -50,
    simulatorMode: input.simulatorMode ?? false,
    isConnected: true,
    lastSeen: now,
    registeredAt: now,
  };
  inMemoryPairedDevices.set(id, paired);
  return paired;
}

/**
 * List all paired devices.
 */
export async function getDevices(): Promise<PairedDevice[]> {
  return Array.from(inMemoryPairedDevices.values());
}

/**
 * Disconnect a paired device.
 */
export async function disconnectDevice(deviceId: string): Promise<void> {
  const dev = inMemoryPairedDevices.get(deviceId);
  if (dev) {
    dev.isConnected = false;
    dev.lastSeen = new Date().toISOString();
  }
}

/**
 * Connect a paired device.
 */
export async function connectDevice(deviceId: string): Promise<void> {
  const dev = inMemoryPairedDevices.get(deviceId);
  if (dev) {
    dev.isConnected = true;
    dev.lastSeen = new Date().toISOString();
  }
}

/**
 * Get device status and telemetry.
 */
export async function getDeviceStatus(deviceId: string): Promise<PairedDevice | null> {
  return inMemoryPairedDevices.get(deviceId) || null;
}

/**
 * Update device heartbeat and telemetry.
 */
export async function updateHeartbeat(deviceId: string, telemetry: DeviceTelemetry): Promise<void> {
  const dev = inMemoryPairedDevices.get(deviceId);
  if (dev) {
    if (telemetry.batteryLevel !== undefined) dev.batteryLevel = telemetry.batteryLevel;
    if (telemetry.signalStrength !== undefined) dev.signalStrength = telemetry.signalStrength;
    dev.lastSeen = new Date().toISOString();
  }
}

/**
 * Toggle simulator mode for a device.
 */
export async function enableSimulatorMode(deviceId: string, enabled: boolean): Promise<void> {
  const dev = inMemoryPairedDevices.get(deviceId);
  if (dev) {
    dev.simulatorMode = enabled;
  }
}

/**
 * Record a hardware event (NEW_SALE, ADD_STOCK, LOW_STOCK_BUTTON, CANCEL).
 */
export async function recordDeviceEvent(
  deviceId: string,
  event: { eventType: string; payload?: any }
): Promise<DeviceEvent> {
  const record: DeviceEvent = {
    id: `evt_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
    deviceId,
    eventType: event.eventType,
    payload: event.payload,
    timestamp: new Date().toISOString(),
  };
  inMemoryDeviceEvents.unshift(record);
  return record;
}

/**
 * Get recent device events.
 */
export async function getDeviceEvents(deviceId: string, limit: number = 20): Promise<DeviceEvent[]> {
  return inMemoryDeviceEvents
    .filter((e) => e.deviceId === deviceId)
    .slice(0, limit);
}
