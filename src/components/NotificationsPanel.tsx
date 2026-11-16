import React, { useState, useEffect, useRef } from 'react';
import { 
  Bell, 
  X, 
  AlertTriangle, 
  CheckCircle2, 
  Check, 
  Package, 
  TrendingUp, 
  Info,
  Trash2
} from 'lucide-react';
import type { PageRoute } from '../types';
import { useAlerts } from '../hooks/useAlerts';

interface NotificationsPanelProps {
  isOpen: boolean;
  onClose: () => void;
  setActivePage: (page: PageRoute) => void;
  triggerRef?: React.RefObject<HTMLButtonElement | null>;
}

function formatAlertTime(isoString: string): string {
  try {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${Math.floor(diffHours / 24)}d ago`;
  } catch {
    return 'Recently';
  }
}

export const NotificationsPanel: React.FC<NotificationsPanelProps> = ({
  isOpen,
  onClose,
  setActivePage,
  triggerRef,
}) => {
  const [readFilter, setReadFilter] = useState<'unread' | 'all'>('unread');
  const [categoryFilter, setCategoryFilter] = useState<'all' | 'inventory' | 'sales' | 'system'>('all');
  const panelRef = useRef<HTMLDivElement>(null);
  const { alerts, unreadCount, markAsRead, markAllAsRead, deleteAlert } = useAlerts();

  // Close on Escape and return focus to bell trigger
  useEffect(() => {
    if (!isOpen) return;

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        triggerRef?.current?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isOpen, onClose, triggerRef]);

  // Click outside listener for desktop popover
  useEffect(() => {
    if (!isOpen) return;

    const onPointerDown = (e: MouseEvent) => {
      const panel = panelRef.current;
      const trigger = triggerRef?.current;
      if (
        panel && 
        !panel.contains(e.target as Node) && 
        trigger && 
        !trigger.contains(e.target as Node)
      ) {
        onClose();
      }
    };

    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [isOpen, onClose, triggerRef]);

  if (!isOpen) return null;

  let filtered = readFilter === 'unread'
    ? alerts.filter(a => !a.isRead && !a.resolvedAt)
    : alerts;

  if (categoryFilter !== 'all') {
    filtered = filtered.filter(a => {
      if (a.category) return a.category === categoryFilter;
      if (categoryFilter === 'inventory') return a.type === 'LOW_STOCK' || a.type === 'OUT_OF_STOCK';
      if (categoryFilter === 'sales') return a.type === 'SALE_COMPLETED' || a.type === 'sales_spike';
      if (categoryFilter === 'system') return a.type === 'system';
      return true;
    });
  }

  return (
    <>
      {/* Mobile backdrop */}
      <div 
        className="fixed inset-0 z-40 bg-[#0B231D]/40 backdrop-blur-xs sm:hidden" 
        onClick={onClose} 
        aria-hidden="true"
      />

      <div 
        ref={panelRef}
        id="notifications-panel" 
        role="region" 
        aria-label="Notifications" 
        className="fixed inset-x-2.5 top-15 sm:inset-x-auto sm:right-0 sm:top-12 w-auto sm:w-[420px] max-w-[calc(100vw-1.25rem)] bg-white rounded-2xl border border-[#DDE9DF] shadow-2xl p-4 z-50 animate-fade-in max-h-[80vh] sm:max-h-[520px] flex flex-col font-sans"
      >
        {/* Header */}
        <div className="flex items-center justify-between pb-3 border-b border-[#DDE9DF] shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-[#E7F3EE] flex items-center justify-center text-[#153D32]">
              <Bell className="w-4 h-4 text-[#23866A]" />
            </div>
            <div>
              <h3 className="font-extrabold text-[#153D32] text-sm">Notifications</h3>
              <p className="text-[11px] text-[#5E6C64]">
                {unreadCount > 0 ? `${unreadCount} unread alert${unreadCount > 1 ? 's' : ''}` : 'All caught up'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {unreadCount > 0 && (
              <button
                type="button"
                onClick={() => markAllAsRead()}
                className="text-[11px] font-bold text-[#23866A] hover:underline cursor-pointer bg-[#E7F3EE] px-2 py-0.5 rounded-md"
              >
                Mark all read
              </button>
            )}
            <button 
              type="button"
              onClick={onClose}
              aria-label="Close notifications"
              className="text-[#5E6C64] hover:text-[#252D29] hover:bg-[#FAF8F2] p-1 rounded-lg cursor-pointer transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Filters Row */}
        <div className="py-2.5 flex items-center justify-between gap-1 border-b border-[#DDE9DF] shrink-0 text-xs">
          {/* Read / Unread */}
          <div className="flex items-center gap-1 bg-[#FAF8F2] p-0.5 rounded-lg border border-[#DDE9DF]">
            <button
              type="button"
              onClick={() => setReadFilter('unread')}
              className={`px-2 py-0.5 rounded-md text-[11px] font-bold transition-all cursor-pointer ${
                readFilter === 'unread'
                  ? 'bg-[#153D32] text-[#FAF8F2] shadow-xs'
                  : 'text-[#5E6C64] hover:text-[#252D29]'
              }`}
            >
              Unread ({unreadCount})
            </button>
            <button
              type="button"
              onClick={() => setReadFilter('all')}
              className={`px-2 py-0.5 rounded-md text-[11px] font-bold transition-all cursor-pointer ${
                readFilter === 'all'
                  ? 'bg-[#153D32] text-[#FAF8F2] shadow-xs'
                  : 'text-[#5E6C64] hover:text-[#252D29]'
              }`}
            >
              All ({alerts.length})
            </button>
          </div>

          {/* Categories */}
          <div className="flex items-center gap-1">
            {(['all', 'inventory', 'sales', 'system'] as const).map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => setCategoryFilter(cat)}
                className={`px-2 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider cursor-pointer transition-colors ${
                  categoryFilter === cat
                    ? 'bg-[#23866A] text-white'
                    : 'text-[#5E6C64] hover:bg-[#FAF8F2]'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </div>

        {/* Notifications List */}
        <div className="space-y-2 overflow-y-auto pr-1 mt-2.5 flex-1 max-h-[380px]">
          {filtered.slice(0, 30).map((alertItem) => {
            const isResolved = Boolean(alertItem.resolvedAt);
            const isCritical = alertItem.priority === 'critical' || alertItem.type === 'OUT_OF_STOCK';
            const isHigh = alertItem.priority === 'high' || alertItem.type === 'LOW_STOCK';
            const timeAgo = formatAlertTime(alertItem.createdAt);

            return (
              <div
                key={alertItem.id}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault();
                    (e.currentTarget as HTMLElement).click();
                  }
                }}
                onClick={() => {
                  if (!alertItem.isRead) markAsRead(alertItem.id);
                  onClose();
                  if (alertItem.deepLink) {
                    if (alertItem.deepLink.includes('/insights')) {
                      setActivePage('insights');
                    } else if (alertItem.deepLink.includes('/inventory')) {
                      setActivePage('inventory');
                    }
                  } else if (alertItem.type === 'LOW_STOCK' || alertItem.type === 'OUT_OF_STOCK' || alertItem.category === 'inventory') {
                    setActivePage('inventory');
                  } else if (alertItem.category === 'sales') {
                    setActivePage('insights');
                  } else {
                    setActivePage('dashboard');
                  }
                }}
                className={`p-3 rounded-xl border text-xs cursor-pointer transition-all ${
                  isResolved
                    ? 'bg-[#E7F3EE]/50 border-[#23866A]/20 text-[#153D32]'
                    : !alertItem.isRead
                    ? isCritical
                      ? 'bg-[#FDF1EF] border-[#EF806D]/30 text-[#252D29]'
                      : isHigh
                      ? 'bg-[#FEF9EB] border-[#D6AE62]/40 text-[#252D29]'
                      : 'bg-[#FAF8F2] border-[#DDE9DF] text-[#252D29]'
                    : 'bg-white border-[#DDE9DF] text-[#5E6C64] opacity-85 hover:opacity-100'
                }`}
              >
                <div className="flex items-center justify-between font-bold mb-1">
                  <div className="flex items-center gap-1.5 truncate">
                    {isResolved ? (
                      <CheckCircle2 className="w-4 h-4 text-[#23866A] shrink-0" />
                    ) : isCritical ? (
                      <AlertTriangle className="w-4 h-4 text-[#EF806D] shrink-0" />
                    ) : alertItem.category === 'sales' ? (
                      <TrendingUp className="w-4 h-4 text-[#23866A] shrink-0" />
                    ) : alertItem.category === 'system' ? (
                      <Info className="w-4 h-4 text-[#23866A] shrink-0" />
                    ) : (
                      <Package className="w-4 h-4 text-[#D6AE62] shrink-0" />
                    )}
                    <span className="truncate font-bold text-[#153D32]">
                      {alertItem.title || alertItem.type.replace(/_/g, ' ')}
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5 shrink-0 ml-2">
                    {isResolved ? (
                      <span className="px-1.5 py-0.5 rounded-full bg-[#E7F3EE] text-[#153D32] text-[9px] font-extrabold uppercase">
                        Resolved
                      </span>
                    ) : isCritical ? (
                      <span className="px-1.5 py-0.5 rounded-full bg-[#FDF1EF] text-[#EF806D] text-[9px] font-extrabold uppercase border border-[#EF806D]/30">
                        Critical
                      </span>
                    ) : isHigh ? (
                      <span className="px-1.5 py-0.5 rounded-full bg-[#FEF9EB] text-[#A07828] text-[9px] font-extrabold uppercase border border-[#D6AE62]/30">
                        High
                      </span>
                    ) : null}

                    {!alertItem.isRead && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          markAsRead(alertItem.id);
                        }}
                        title="Mark as read"
                        aria-label="Mark notification as read"
                        className="p-1 rounded-md bg-white hover:bg-[#FAF8F2] text-[#23866A] border border-[#DDE9DF] transition-all cursor-pointer flex items-center gap-1 text-[10px] font-bold"
                      >
                        <Check className="w-3 h-3 text-[#23866A]" />
                      </button>
                    )}

                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        deleteAlert(alertItem.id);
                      }}
                      title="Delete alert"
                      aria-label="Delete notification"
                      className="p-1 rounded-md bg-white hover:bg-[#FDF1EF] text-[#5E6C64] hover:text-[#EF806D] border border-[#DDE9DF] transition-all cursor-pointer"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>

                    <span className="text-[10px] text-[#5E6C64] font-medium ml-1">
                      {timeAgo}
                    </span>
                  </div>
                </div>

                <p className="text-[11px] font-normal leading-relaxed text-[#252D29]">
                  {alertItem.message}
                </p>
              </div>
            );
          })}

          {filtered.length === 0 && (
            <div className="py-10 text-center text-[#5E6C64] space-y-2">
              <div className="w-10 h-10 rounded-full bg-[#E7F3EE] flex items-center justify-center text-[#23866A] mx-auto">
                <CheckCircle2 className="w-5 h-5 text-[#23866A]" />
              </div>
              <p className="font-extrabold text-[#153D32] text-xs">All caught up!</p>
              <p className="text-[11px] text-[#5E6C64]">
                {readFilter === 'unread' ? 'No unread notifications in this category.' : 'No notifications recorded yet.'}
              </p>
            </div>
          )}
        </div>
      </div>
    </>
  );
};
