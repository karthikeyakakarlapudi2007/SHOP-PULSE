/**
 * @file scaleService.ts
 * @description Smart Weighing Scale service providing live weight processing, tare, and auto-calculation.
 */

export interface ScaleReading {
  weight: number;
  tare: number;
  netWeight: number;
  isStable: boolean;
}

export interface CalculatedProductQuantity {
  productName: string;
  quantity: number;
  totalPrice: number;
}

class ScaleService {
  private currentTare: number = 0;
  private currentReading: ScaleReading = {
    weight: 0,
    tare: 0,
    netWeight: 0,
    isStable: true,
  };

  public clearTare(): void {
    this.currentTare = 0;
    this.currentReading.tare = 0;
    this.currentReading.netWeight = this.currentReading.weight;
  }

  public processRawWeight(weight: number): ScaleReading {
    const net = Math.max(0, Number((weight - this.currentTare).toFixed(3)));
    this.currentReading = {
      weight,
      tare: this.currentTare,
      netWeight: net,
      isStable: true,
    };
    return { ...this.currentReading };
  }

  public tare(tareWeight?: number): ScaleReading {
    this.currentTare = tareWeight !== undefined ? tareWeight : this.currentReading.weight;
    const net = Math.max(0, Number((this.currentReading.weight - this.currentTare).toFixed(3)));
    this.currentReading.tare = this.currentTare;
    this.currentReading.netWeight = net;
    return { ...this.currentReading };
  }

  public getLatestReading(): ScaleReading {
    return { ...this.currentReading };
  }

  public calculateProductQuantity(
    product: { id: string; name: string; unit: string; price: number },
    reading: { netWeight: number }
  ): CalculatedProductQuantity {
    const quantity = Number(reading.netWeight.toFixed(3));
    const totalPrice = Number((quantity * product.price).toFixed(2));
    return {
      productName: product.name,
      quantity,
      totalPrice,
    };
  }
}

export const scaleService = new ScaleService();

