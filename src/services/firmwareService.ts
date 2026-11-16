/**
 * @file firmwareService.ts
 * @description Firmware update checking and OTA update scheduling service.
 */

export interface FirmwareUpdateInfo {
  isUpdateAvailable: boolean;
  latestVersion: string;
  downloadUrl?: string;
  releaseNotes?: string;
}

export interface OTAScheduleResult {
  deviceId: string;
  version: string;
  status: string;
  scheduledAt: string;
}

class FirmwareService {
  private readonly LATEST_VERSION = '1.3.0';
  private readonly DOWNLOAD_URL = 'https://firmware.shelfora.com/ota/v1.3.0/firmware.bin';

  public async checkForUpdate(device: {
    id: string;
    firmwareVersion?: string;
    [key: string]: any;
  }): Promise<FirmwareUpdateInfo> {
    const current = device.firmwareVersion || '1.0.0';
    const isUpdateAvailable = current !== this.LATEST_VERSION;
    return {
      isUpdateAvailable,
      latestVersion: this.LATEST_VERSION,
      downloadUrl: isUpdateAvailable ? this.DOWNLOAD_URL : undefined,
      releaseNotes: 'Performance improvements, smart weighing accuracy optimizations, and bug fixes.',
    };
  }

  public async scheduleOTAUpdate(deviceId: string, version: string): Promise<OTAScheduleResult> {
    return {
      deviceId,
      version,
      status: 'AVAILABLE',
      scheduledAt: new Date().toISOString(),
    };
  }
}

export const firmwareService = new FirmwareService();

