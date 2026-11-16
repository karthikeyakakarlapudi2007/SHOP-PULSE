/**
 * @file bluetoothService.ts
 * @description Web Bluetooth connection layer with graceful simulation fallback.
 */

export interface BluetoothPairResult {
  fallbackToSimulator: boolean;
  device?: any;
  error?: string;
}

class BluetoothService {
  public isBluetoothSupported(): boolean {
    if (typeof navigator === 'undefined') return false;
    return typeof (navigator as any).bluetooth !== 'undefined';
  }

  public async scanAndPair(): Promise<BluetoothPairResult> {
    if (!this.isBluetoothSupported()) {
      return {
        fallbackToSimulator: true,
      };
    }

    try {
      const device = await (navigator as any).bluetooth.requestDevice({
        acceptAllDevices: true,
      });
      return {
        fallbackToSimulator: false,
        device,
      };
    } catch (err: any) {
      return {
        fallbackToSimulator: true,
        error: err?.message,
      };
    }
  }
}

export const bluetoothService = new BluetoothService();

