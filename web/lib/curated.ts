import fs from 'fs';
import path from 'path';

export interface ForecastData {
  risk_band: string;
  p_exceed: number;
  model_version: string;
  top_drivers: string[];
}

export interface EnvData {
  wave_height_m: number | null;
  water_temperature_c: number | null;
}

export interface Beach {
  id: string;
  name: string;
  county: string;
  region: string;
  latitude: number;
  longitude: number;
  support_status: string;
  forecast?: ForecastData;
  env?: EnvData;
}

export interface RegionalSummary {
  region: string;
  station_count: number;
  avg_water_temp_c: number;
  avg_wave_height_m: number;
  high_risk_count: number;
}

export interface ParentBeach {
  id: string;
  name: string;
  county: string;
  region: string;
  latitude: number;
  longitude: number;
  station_count: number;
  member_beach_ids: string[];
}

function readJson<T>(filename: string): T {
  const filePath = path.join(process.cwd(), 'public', 'data', filename);
  try {
    const data = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(data);
  } catch (e) {
    console.error(`Failed to read ${filename}:`, e);
    return [] as any as T;
  }
}

export function listBeaches(): Beach[] {
  return readJson<Beach[]>('beaches.json');
}

export function regionalSummary(): RegionalSummary[] {
  return readJson<RegionalSummary[]>('regional_summary.json');
}

export function siteForMap(): ParentBeach[] {
  return readJson<ParentBeach[]>('parent_beaches.json');
}
