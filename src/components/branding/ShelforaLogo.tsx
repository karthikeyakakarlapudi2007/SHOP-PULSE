import React from 'react';

export interface ShelforaLogoProps {
  /**
   * - 'full': Stacked symbol + SHELFORA wordmark + optional tagline
   * - 'compact': Symbol only
   * - 'horizontal': Symbol on left, wordmark on right
   * - 'dark': Symbol on left, light wordmark for dark / forest backgrounds
   */
  variant?: 'full' | 'compact' | 'horizontal' | 'dark';
  size?: 'sm' | 'md' | 'lg' | 'xl';
  showTagline?: boolean;
  className?: string;
  onClick?: () => void;
}

/**
 * Shelfora Brand Emblem (SVG Symbol)
 * Concept: Modern grocery shelf tiers + organic freshness leaf + smart analytics growth spark.
 */
export const ShelforaSymbol: React.FC<{ size?: 'sm' | 'md' | 'lg' | 'xl'; className?: string }> = ({
  size = 'md',
  className = '',
}) => {
  const sizeMap = {
    sm: 'w-6 h-6',
    md: 'w-8 h-8',
    lg: 'w-10 h-10',
    xl: 'w-12 h-12',
  };

  return (
    <svg
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`${sizeMap[size]} shrink-0 ${className}`}
      aria-hidden="true"
    >
      <defs>
        {/* Deep Forest Green Base Gradient */}
        <linearGradient id="shelfora-forest" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#123D32" />
          <stop offset="100%" stopColor="#0A241D" />
        </linearGradient>

        {/* Emerald Green Shelf Gradient */}
        <linearGradient id="shelfora-emerald" x1="0" y1="12" x2="36" y2="44" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#1EA785" />
          <stop offset="100%" stopColor="#16866A" />
        </linearGradient>

        {/* Analytics Growth Spark Gradient */}
        <linearGradient id="shelfora-spark" x1="28" y1="6" x2="44" y2="22" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#16866A" />
          <stop offset="100%" stopColor="#E8F3ED" />
        </linearGradient>

        {/* Soft Mint Leaf Gradient */}
        <linearGradient id="shelfora-leaf" x1="8" y1="8" x2="24" y2="24" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#E8F3ED" />
          <stop offset="60%" stopColor="#16866A" />
          <stop offset="100%" stopColor="#123D32" />
        </linearGradient>
      </defs>

      {/* Rounded Container */}
      <rect
        x="2"
        y="2"
        width="44"
        height="44"
        rx="12"
        fill="url(#shelfora-forest)"
      />

      {/* Subtle outer stroke */}
      <rect
        x="2.5"
        y="2.5"
        width="43"
        height="43"
        rx="11.5"
        stroke="#E8F3ED"
        strokeOpacity="0.25"
        strokeWidth="1"
      />

      {/* Grocery Shelf Tier 1 (Base Shelf / Basket Cradle) */}
      <path
        d="M11 35C11 33.3431 12.3431 32 14 32H34C35.6569 32 37 33.3431 37 35C37 36.6569 35.6569 38 34 38H14C12.3431 38 11 36.6569 11 35Z"
        fill="url(#shelfora-emerald)"
      />

      {/* Shelf Tier 2 (Middle Inventory Rail) */}
      <rect
        x="13"
        y="25"
        width="22"
        height="4"
        rx="2"
        fill="#E8F3ED"
        fillOpacity="0.95"
      />

      {/* Shelf Tier 3 (Upper Shelf / Organized Items) */}
      <rect
        x="17"
        y="19"
        width="14"
        height="3.5"
        rx="1.75"
        fill="#FAF8F2"
      />

      {/* Freshness Leaf: Organic Arch on Upper Left */}
      <path
        d="M12 21C11.5 14.5 15.5 10 21 9.5C21.5 14.5 17.5 19 12 21Z"
        fill="url(#shelfora-leaf)"
      />
      <path
        d="M13.5 19.5C14.5 16 16.5 13.5 19.5 11"
        stroke="#E8F3ED"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeOpacity="0.9"
      />

      {/* Smart Analytics Growth Spark on Upper Right */}
      <path
        d="M34 8L35.5 12.5L40 14L35.5 15.5L34 20L32.5 15.5L28 14L32.5 12.5L34 8Z"
        fill="#16866A"
      />
      <circle cx="34" cy="14" r="1.5" fill="#FAF8F2" />
    </svg>
  );
};

export const ShelforaLogo: React.FC<ShelforaLogoProps> = ({
  variant = 'horizontal',
  size = 'md',
  showTagline = false,
  className = '',
  onClick,
}) => {
  const isDark = variant === 'dark';
  const isCompact = variant === 'compact';
  const isFull = variant === 'full';

  const textSizes = {
    sm: 'text-sm tracking-[0.1em]',
    md: 'text-base tracking-[0.12em]',
    lg: 'text-xl tracking-[0.14em]',
    xl: 'text-2xl tracking-[0.16em]',
  };

  const taglineSizes = {
    sm: 'text-[9px]',
    md: 'text-[10px]',
    lg: 'text-xs',
    xl: 'text-sm',
  };

  if (isCompact) {
    return (
      <div 
        onClick={onClick}
        role={onClick ? 'button' : undefined}
        tabIndex={onClick ? 0 : undefined}
        className={`inline-flex items-center justify-center ${onClick ? 'cursor-pointer' : ''} ${className}`}
      >
        <ShelforaSymbol size={size} />
      </div>
    );
  }

  if (isFull) {
    return (
      <div
        onClick={onClick}
        role={onClick ? 'button' : undefined}
        tabIndex={onClick ? 0 : undefined}
        className={`flex flex-col items-center text-center gap-2 select-none ${onClick ? 'cursor-pointer' : ''} ${className}`}
      >
        <ShelforaSymbol size={size} />
        <div className="flex flex-col items-center">
          <span className={`font-black font-sans uppercase ${isDark ? 'text-[#FAF8F2]' : 'text-[#123D32]'} ${textSizes[size]}`}>
            SHELFORA
          </span>
          {showTagline && (
            <span className={`font-medium ${isDark ? 'text-[#E8F3ED]' : 'text-[#16866A]'} ${taglineSizes[size]} tracking-tight`}>
              Smarter Grocery Management.
            </span>
          )}
        </div>
      </div>
    );
  }

  // Horizontal or Dark
  return (
    <div
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      className={`inline-flex items-center gap-2.5 select-none ${onClick ? 'cursor-pointer' : ''} ${className}`}
    >
      <ShelforaSymbol size={size} />
      <div className="flex flex-col justify-center text-left leading-none">
        <div className="flex items-center gap-1">
          <span className={`font-black font-sans uppercase ${isDark ? 'text-[#FAF8F2]' : 'text-[#123D32]'} ${textSizes[size]}`}>
            SHELFORA
          </span>
          <span className="w-1.5 h-1.5 rounded-full bg-[#16866A] inline-block mb-0.5" />
        </div>
        {showTagline && (
          <span className={`font-medium mt-1 ${isDark ? 'text-[#E8F3ED]/90' : 'text-[#16866A]'} ${taglineSizes[size]}`}>
            Smarter Grocery Management.
          </span>
        )}
      </div>
    </div>
  );
};
