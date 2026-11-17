import React, { useEffect, useState } from 'react';
import { ImageOff } from 'lucide-react';
import { fetchBlob } from '../../api/documentPrep';

interface AuthImageProps {
  src: string;
  alt: string;
  className?: string;
  /** Changes force a reload (e.g. after a rotation or re-processing). */
  version?: string | number;
  children?: React.ReactNode;
}

/** Private page images need the auth header, so they are fetched and shown as blob URLs. */
export const AuthImage: React.FC<AuthImageProps> = ({ src, alt, className, version, children }) => {
  const key = `${src}#${version ?? ''}`;
  // State is tagged with the request it belongs to; a stale result simply reads as loading.
  const [state, setState] = useState<{ key: string; url: string | null; failed: boolean }>({
    key: '',
    url: null,
    failed: false,
  });

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    fetchBlob(src)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ key, url: objectUrl, failed: false });
      })
      .catch(() => {
        if (!cancelled) setState({ key, url: null, failed: true });
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src, key]);

  const current = state.key === key;
  const failed = current && state.failed;
  const url = current ? state.url : null;

  if (failed) {
    return (
      <div className={`flex flex-col items-center justify-center gap-1 text-[#5E6C64] text-xs ${className ?? ''}`}>
        <ImageOff className="w-5 h-5" aria-hidden="true" />
        Preview unavailable
      </div>
    );
  }
  if (!url) {
    return <div className={`animate-pulse bg-[#F3EFE3] ${className ?? ''}`} aria-label="Loading preview" />;
  }
  return (
    <div className="relative inline-block max-w-full">
      <img src={url} alt={alt} className={className} draggable={false} />
      {children}
    </div>
  );
};
