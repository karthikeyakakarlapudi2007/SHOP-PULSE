/**
 * @file deviceSimulator.ts
 * @description High-fidelity hardware device and weight sensor simulator.
 */

import { scaleService, type ScaleReading } from './scaleService';

class DeviceSimulator {
  public async triggerNewSale(customerOrNote: string = 'Walk-in Kirana shopper'): Promise<{
    eventType: string;
    payload: { customer: string; quickCart: boolean };
    timestamp: string;
  }> {
    return {
      eventType: 'NEW_SALE',
      payload: { customer: customerOrNote, quickCart: true },
      timestamp: new Date().toISOString(),
    };
  }

  public async triggerLowStock(productName: string): Promise<{
    eventType: string;
    payload: { productName: string };
    timestamp: string;
  }> {
    return {
      eventType: 'LOW_STOCK_BUTTON',
      payload: { productName },
      timestamp: new Date().toISOString(),
    };
  }

  public async simulateWeight(weight: number, _productName?: string): Promise<ScaleReading> {
    return scaleService.processRawWeight(weight);
  }
}

export const deviceSimulator = new DeviceSimulator();

