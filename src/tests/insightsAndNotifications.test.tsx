import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { Insights } from '../pages/Insights';
import { NotificationsPanel } from '../components/NotificationsPanel';
import { LanguageProvider } from '../i18n/LanguageContext';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    user: { uid: 'test-user', email: 'owner@example.com' },
    loading: false,
  }),
}));


vi.mock('../api/insights', () => ({
  insightsApi: {
    getSalesInsights: vi.fn().mockResolvedValue({
      overview: {
        total_sales: 12500,
        transaction_count: 14,
        average_transaction_value: 892.8,
        previous_period_sales: 10400,
        previous_period_transactions: 12,
        sales_growth_rate: 20.2,
        period: '7d',
        start_date: '2026-11-04T00:00:00Z',
        end_date: '2026-11-11T00:00:00Z'
      },
      performance: {
        best_selling: [
          {
            product_id: 'p1',
            product_name: 'Basmati Rice 5kg',
            category: 'Grains',
            quantity_sold: 10,
            revenue: 5000,
            unit: 'bag',
            growth_rate: 15.0
          }
        ],
        slow_moving: [],
        increasing_sales: [],
        declining_sales: []
      },
      trends: {
        interval: 'daily',
        points: [
          { date: '2026-11-10', label: '10 Nov', revenue: 2500, transaction_count: 3 },
          { date: '2026-11-11', label: '11 Nov', revenue: 3200, transaction_count: 4 }
        ],
        peak_day: '11 Nov',
        peak_revenue: 3200
      },
      has_sufficient_data: true,
      data_summary_note: null
    }),
    getInventoryInsights: vi.fn().mockResolvedValue({
      counts: {
        in_stock: 30,
        low_stock: 4,
        out_of_stock: 2,
        overstocked: 1,
        needs_attention: 6,
        total_products: 37
      },
      items: [
        {
          product_id: 'p2',
          product_name: 'Sunflower Oil 1L',
          category: 'Oil',
          current_stock: 2,
          minimum_stock_threshold: 10,
          unit: 'bottle',
          status: 'LOW STOCK',
          recommended_action: 'Order at least 15 bottles',
          urgency: 'high',
          selling_price: 160,
          purchase_price: 130,
          is_threshold_configured: true
        }
      ],
      has_sufficient_data: true
    }),
    getAiInsights: vi.fn().mockResolvedValue({
      insights: [
        {
          id: 'ai-1',
          type: 'positive',
          category: 'sales',
          title: 'Top Revenue Driver: Basmati Rice 5kg',
          message: 'Basmati Rice generated ₹5,000 across 10 bags sold over the last 7 days.',
          metric: '₹5,000',
          grounded_data_points: ['Product: Basmati Rice 5kg', 'Revenue: ₹5,000'],
          suggested_action: 'Verify supplier stock'
        }
      ],
      overall_business_health: 'Healthy',
      has_sufficient_data: true,
      note: null
    })
  }
}));

vi.mock('../hooks/useAlerts', () => ({
  useAlerts: () => ({
    alerts: [
      {
        id: 'a1',
        title: 'Low Stock Alert: Sunflower Oil',
        message: 'Sunflower Oil has 2 bottles remaining (minimum threshold: 10 bottles).',
        priority: 'high',
        type: 'LOW_STOCK',
        category: 'inventory',
        isRead: false,
        createdAt: new Date().toISOString()
      },
      {
        id: 'a2',
        title: 'Daily Sales Summary',
        message: "Today's sales reached ₹3,200 across 4 transactions.",
        priority: 'medium',
        type: 'SALE_COMPLETED',
        category: 'sales',
        isRead: false,
        createdAt: new Date().toISOString()
      }
    ],
    unreadCount: 2,
    markAsRead: vi.fn(),
    markAllAsRead: vi.fn(),
    deleteAlert: vi.fn(),
    loading: false
  })
}));

describe('AI Insights and Smart Notifications Frontend Module', () => {
  it('renders the Insights page with module navigation and action headers', () => {
    const html = renderToStaticMarkup(
      <LanguageProvider>
        <Insights />
      </LanguageProvider>
    );

    // Module primary tabs
    expect(html).toContain('Sales Insights');
    expect(html).toContain('Inventory Insights');
    expect(html).toContain('AI Intelligence');

    // Action header
    expect(html).toContain('AI Insights &amp; Analytics');
    expect(html).toContain('Refresh Analytics');

    // Sales Overview cards
    expect(html).toContain('Total Revenue');
    expect(html).toContain('Transactions');
    expect(html).toContain('Average Bill Value');
    expect(html).toContain('Prior Period Sales');

    // Product performance section
    expect(html).toContain('Product Performance');
    expect(html).toContain('Best Selling');
    expect(html).toContain('Slow Moving');
    expect(html).toContain('Rising Sales');
    expect(html).toContain('Declining Sales');
  });

  it('renders the NotificationsPanel with unread count, category filters, and action controls', () => {
    const html = renderToStaticMarkup(
      <NotificationsPanel
        isOpen={true}
        onClose={vi.fn()}
        setActivePage={vi.fn()}
      />
    );

    expect(html).toContain('Notifications');
    expect(html).toContain('Unread (2)');
    expect(html).toContain('Mark all read');
    expect(html).toContain('inventory');
    expect(html).toContain('sales');
    expect(html).toContain('system');
    expect(html).toContain('Low Stock Alert: Sunflower Oil');
    expect(html).toContain('Daily Sales Summary');
  });
});
