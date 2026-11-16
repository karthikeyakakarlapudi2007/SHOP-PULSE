import React from 'react';
import { Loader2 } from 'lucide-react';

// React 19 passes `ref` as a regular prop, so it reaches the <button> through ...props.
interface ButtonProps extends React.ComponentPropsWithRef<'button'> {
  variant?: 'primary' | 'secondary' | 'danger' | 'outline' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  icon?: React.ReactNode;
  /** Shows a spinner, disables the button and marks it busy while an operation runs. */
  loading?: boolean;
  children: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'primary',
  size = 'md',
  icon,
  loading = false,
  children,
  className = '',
  disabled,
  ...props
}) => {
  const baseStyles = 'font-bold rounded-xl transition-all duration-150 inline-flex items-center justify-center gap-2 cursor-pointer active:scale-[0.99] disabled:opacity-50 disabled:pointer-events-none disabled:cursor-not-allowed select-none focus-visible:outline-2 focus-visible:outline-offset-2';

  const variantStyles = {
    primary: 'bg-[#153D32] hover:bg-[#0F2D25] active:bg-[#0B231D] text-[#FAF8F2] border border-[#153D32] shadow-card focus-visible:outline-[#153D32]',
    secondary: 'bg-white hover:bg-[#FAF8F2] active:bg-[#E7F3EE] text-[#252D29] border border-[#DDE9DF] hover:border-[#23866A]/40 focus-visible:outline-[#153D32]',
    danger: 'bg-[#EF806D] hover:bg-[#DC6F5C] active:bg-[#C85C4A] text-white border border-[#EF806D] shadow-card focus-visible:outline-[#EF806D]',
    outline: 'bg-transparent hover:bg-[#E7F3EE] text-[#153D32] border border-[#DDE9DF] active:bg-[#E7F3EE]/80 focus-visible:outline-[#153D32]',
    ghost: 'bg-transparent hover:bg-[#E7F3EE] text-[#153D32] border border-transparent shadow-none focus-visible:outline-[#153D32]',
  };

  const sizeStyles = {
    sm: 'px-3 py-1.5 text-xs sm:text-sm min-h-[36px]',
    md: 'px-4 py-2.5 text-sm sm:text-base min-h-[44px]',
    lg: 'px-6 py-3 text-base sm:text-lg font-bold min-h-[48px]',
  };

  const shownIcon = loading ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : icon;

  return (
    <button
      className={`${baseStyles} ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {shownIcon && <span className="shrink-0">{shownIcon}</span>}
      <span>{children}</span>
    </button>
  );
};
