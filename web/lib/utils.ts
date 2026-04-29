import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatPercent(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return `${Math.round(value * 100)}%`;
}

export function formatWaveFeet(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return `${(value * 3.28084).toFixed(1)} ft`;
}

export function formatWaterFahrenheit(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return `${Math.round((value * 9) / 5 + 32)}°F`;
}

export function formatPacificTimestamp(value: string | null | undefined) {
  if (!value) {
    return "Unknown";
  }

  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(new Date(value));
}

export function formatPacificDate(value: string | null | undefined) {
  if (!value) {
    return "Unknown";
  }

  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

export function formatRelativeSampleDate(value: string | null | undefined) {
  if (!value) {
    return "No recent sample";
  }

  const sampleDate = new Date(value);
  const now = new Date();
  const diffMs = now.getTime() - sampleDate.getTime();
  const diffDays = Math.max(Math.round(diffMs / 86400000), 0);

  if (diffDays === 0) {
    return "Sampled today";
  }
  if (diffDays === 1) {
    return "Sampled 1 day ago";
  }
  return `Sampled ${diffDays} days ago`;
}
