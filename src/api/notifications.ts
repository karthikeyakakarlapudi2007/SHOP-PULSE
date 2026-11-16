/**
 * @file notifications.ts
 * @description Frontend API client for Shelfora Smart Notifications module.
 */

import { apiClient } from './client';

export interface NotificationItem {
  id: string;
  user_id: string;
  shop_id: string;
  title: string;
  message: string;
  category: 'inventory' | 'sales' | 'system';
  priority: 'low' | 'medium' | 'high' | 'critical';
  is_read: boolean;
  product_id?: string;
  transaction_id?: string;
  deep_link?: string;
  event_key?: string;
  created_at: string;
  resolved_at?: string;
}

export interface PaginatedNotifications {
  items: NotificationItem[];
  total: number;
  unread_count: number;
  skip: number;
  limit: number;
}

export interface NotificationPreferences {
  sales_alerts: boolean;
  inventory_alerts: boolean;
  system_alerts: boolean;
  in_app_enabled: boolean;
  push_enabled: boolean;
  daily_summary_enabled: boolean;
}

export interface NotificationFilters {
  category?: string;
  priority?: string;
  is_read?: boolean;
  skip?: number;
  limit?: number;
}

export const notificationsApi = {
  getNotifications: async (filters: NotificationFilters = {}): Promise<PaginatedNotifications> => {
    const params = new URLSearchParams();
    if (filters.category) params.append('category', filters.category);
    if (filters.priority) params.append('priority', filters.priority);
    if (filters.is_read !== undefined) params.append('is_read', String(filters.is_read));
    if (filters.skip !== undefined) params.append('skip', String(filters.skip));
    if (filters.limit !== undefined) params.append('limit', String(filters.limit));

    return apiClient.get<PaginatedNotifications>(`/api/v1/notifications?${params.toString()}`);
  },

  getUnreadCount: async (): Promise<number> => {
    const res = await apiClient.get<{ count: number }>('/api/v1/notifications/unread-count');
    return res.count;
  },

  markAsRead: async (id: string): Promise<NotificationItem> => {
    return apiClient.patch<NotificationItem>(`/api/v1/notifications/${id}/read`);
  },

  markAllAsRead: async (): Promise<{ message: string; marked_count: number }> => {
    return apiClient.post<{ message: string; marked_count: number }>('/api/v1/notifications/mark-all-read');
  },

  deleteNotification: async (id: string): Promise<void> => {
    await apiClient.delete(`/api/v1/notifications/${id}`);
  },

  getPreferences: async (): Promise<NotificationPreferences> => {
    return apiClient.get<NotificationPreferences>('/api/v1/notifications/preferences');
  },

  updatePreferences: async (prefs: NotificationPreferences): Promise<NotificationPreferences> => {
    return apiClient.put<NotificationPreferences>('/api/v1/notifications/preferences', prefs);
  },

  registerDeviceToken: async (token: string, platform: string = 'android'): Promise<void> => {
    await apiClient.post('/api/v1/notifications/devices', { token, platform });
  },

  unregisterDeviceToken: async (token: string): Promise<void> => {
    await apiClient.delete(`/api/v1/notifications/devices/${encodeURIComponent(token)}`);
  },

  triggerEvaluation: async (): Promise<{ message: string; alerts_generated: number; notifications: NotificationItem[] }> => {
    return apiClient.post<{ message: string; alerts_generated: number; notifications: NotificationItem[] }>('/api/v1/notifications/trigger-evaluation');
  },
};

