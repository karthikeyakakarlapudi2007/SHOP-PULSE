/**
 * @file insights.ts
 * @description Frontend API client for Shelfora AI Insights module.
 */

import { apiClient } from './client';

export interface SalesOverview {
  total_sales: number;
  transaction_count: number;
  average_transaction_value: number;
  previous_period_sales: number;
  previous_period_transactions: number;
  sales_growth_rate: number | null;
  period: string;
  start_date: string;
  end_date: string;
}

export interface ProductPerformanceItem {
  product_id: string;
  product_name: string;
  category: string;
  quantity_sold: number;
  revenue: number;
  unit: string;
  previous_quantity_sold: number;
  growth_rate: number | null;
}

export interface ProductPerformance {
  best_selling: ProductPerformanceItem[];
  slow_moving: ProductPerformanceItem[];
  increasing_sales: ProductPerformanceItem[];
  declining_sales: ProductPerformanceItem[];
}

export interface SalesTrendPoint {
  date: string;
  label: string;
  revenue: number;
  transaction_count: number;
}

export interface SalesTrends {
  interval: string;
  points: SalesTrendPoint[];
  peak_day: string | null;
  peak_revenue: number;
}

export interface SalesInsightsData {
  overview: SalesOverview;
  performance: ProductPerformance;
  trends: SalesTrends;
  has_sufficient_data: boolean;
  data_summary_note: string | null;
}


export interface InventoryStatusCounts {
  in_stock: number;
  low_stock: number;
  out_of_stock: number;
  overstocked: number;
  needs_attention: number;
  total_products: number;
}

export interface InventoryInsightItem {
  product_id: string;
  product_name: string;
  category: string;
  current_stock: number;
  minimum_stock_threshold: number;
  unit: string;
  status: 'IN STOCK' | 'LOW STOCK' | 'OUT OF STOCK' | 'OVERSTOCKED' | 'NEEDS ATTENTION';
  recommended_action: string;
  urgency: 'critical' | 'high' | 'medium' | 'low';
  selling_price: number;
  purchase_price: number | null;
  last_updated: string | null;
  is_threshold_configured: boolean;
}

export interface InventoryInsightsData {
  counts: InventoryStatusCounts;
  items: InventoryInsightItem[];
  has_sufficient_data: boolean;
}

export interface AiInsightCard {
  id: string;
  type: 'critical' | 'warning' | 'positive' | 'info';
  category: 'sales' | 'inventory' | 'action';
  title: string;
  message: string;
  metric: string | null;
  grounded_data_points: string[];
  suggested_action: string | null;
}

export interface AiInsightsData {
  insights: AiInsightCard[];
  overall_business_health: string;
  has_sufficient_data: boolean;
  note: string | null;
}

export const insightsApi = {
  getSalesInsights: async (
    period: 'today' | '7d' | '30d' | '90d' | 'custom' = '7d',
    startDate?: string,
    endDate?: string
  ): Promise<SalesInsightsData> => {
    let url = `/api/v1/insights/sales?period=${period}`;
    if (period === 'custom' && startDate && endDate) {
      url += `&start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`;
    }
    return apiClient.get<SalesInsightsData>(url);
  },

  getInventoryInsights: async (): Promise<InventoryInsightsData> => {
    return apiClient.get<InventoryInsightsData>('/api/v1/insights/inventory');
  },

  getAiInsights: async (): Promise<AiInsightsData> => {
    return apiClient.get<AiInsightsData>('/api/v1/insights/ai-summary');
  },

};
