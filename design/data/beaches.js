// 50+ California beaches with geo coords and mock forecast data
window.BEACHES = [
  // San Diego County
  { id: 'imperial-beach', name: 'Imperial Beach', county: 'San Diego', region: 'SoCal', lat: 32.583, lon: -117.133, risk: 'Very High', p: 0.82, temp: 63, waveFt: 2.1, period: 9, wind: 8, uv: 7, tide: 'Rising', crowd: 'Light' },
  { id: 'coronado', name: 'Coronado Beach', county: 'San Diego', region: 'SoCal', lat: 32.686, lon: -117.183, risk: 'Low', p: 0.08, temp: 64, waveFt: 2.5, period: 10, wind: 6, uv: 8, tide: 'High', crowd: 'Moderate' },
  { id: 'ocean-beach-sd', name: 'Ocean Beach', county: 'San Diego', region: 'SoCal', lat: 32.748, lon: -117.252, risk: 'Moderate', p: 0.31, temp: 63, waveFt: 3.2, period: 11, wind: 7, uv: 8, tide: 'Rising', crowd: 'Busy' },
  { id: 'scripps-pier', name: 'Scripps Pier', county: 'San Diego', region: 'SoCal', lat: 32.866, lon: -117.257, risk: 'Moderate', p: 0.29, temp: 62, waveFt: 2.8, period: 11, wind: 5, uv: 7, tide: 'High', crowd: 'Light' },
  { id: 'la-jolla-shores', name: 'La Jolla Shores', county: 'San Diego', region: 'SoCal', lat: 32.858, lon: -117.256, risk: 'Low', p: 0.12, temp: 63, waveFt: 2.0, period: 10, wind: 4, uv: 8, tide: 'High', crowd: 'Busy' },
  { id: 'del-mar', name: 'Del Mar City Beach', county: 'San Diego', region: 'SoCal', lat: 32.961, lon: -117.266, risk: 'Low', p: 0.10, temp: 63, waveFt: 3.0, period: 12, wind: 5, uv: 8, tide: 'Rising', crowd: 'Moderate' },
  { id: 'cardiff', name: 'Cardiff State Beach', county: 'San Diego', region: 'SoCal', lat: 33.018, lon: -117.281, risk: 'Low', p: 0.14, temp: 63, waveFt: 3.2, period: 11, wind: 6, uv: 8, tide: 'Rising', crowd: 'Moderate' },
  { id: 'swamis', name: "Swami's", county: 'San Diego', region: 'SoCal', lat: 33.036, lon: -117.294, risk: 'Low', p: 0.11, temp: 63, waveFt: 3.6, period: 13, wind: 4, uv: 8, tide: 'High', crowd: 'Busy' },
  { id: 'oceanside', name: 'Oceanside Pier', county: 'San Diego', region: 'SoCal', lat: 33.194, lon: -117.384, risk: 'Moderate', p: 0.38, temp: 64, waveFt: 2.6, period: 10, wind: 7, uv: 8, tide: 'Rising', crowd: 'Busy' },

  // Orange County
  { id: 'san-onofre', name: 'San Onofre', county: 'Orange', region: 'SoCal', lat: 33.373, lon: -117.566, risk: 'Low', p: 0.09, temp: 64, waveFt: 3.4, period: 12, wind: 5, uv: 8, tide: 'High', crowd: 'Moderate' },
  { id: 'trestles', name: 'Lower Trestles', county: 'Orange', region: 'SoCal', lat: 33.385, lon: -117.589, risk: 'Low', p: 0.07, temp: 64, waveFt: 4.0, period: 13, wind: 3, uv: 8, tide: 'High', crowd: 'Busy' },
  { id: 'san-clemente', name: 'San Clemente Pier', county: 'Orange', region: 'SoCal', lat: 33.418, lon: -117.624, risk: 'Moderate', p: 0.27, temp: 64, waveFt: 3.2, period: 11, wind: 5, uv: 8, tide: 'Rising', crowd: 'Busy' },
  { id: 'doheny', name: 'Doheny State Beach', county: 'Orange', region: 'SoCal', lat: 33.461, lon: -117.683, risk: 'High', p: 0.58, temp: 64, waveFt: 2.2, period: 10, wind: 6, uv: 8, tide: 'Low', crowd: 'Moderate' },
  { id: 'salt-creek', name: 'Salt Creek', county: 'Orange', region: 'SoCal', lat: 33.478, lon: -117.718, risk: 'Low', p: 0.13, temp: 64, waveFt: 3.0, period: 11, wind: 5, uv: 8, tide: 'Rising', crowd: 'Moderate' },
  { id: 'laguna', name: 'Main Beach, Laguna', county: 'Orange', region: 'SoCal', lat: 33.542, lon: -117.787, risk: 'Low', p: 0.15, temp: 65, waveFt: 2.6, period: 10, wind: 4, uv: 8, tide: 'High', crowd: 'Busy' },
  { id: 'newport', name: 'Newport Beach Pier', county: 'Orange', region: 'SoCal', lat: 33.606, lon: -117.929, risk: 'Moderate', p: 0.33, temp: 64, waveFt: 3.2, period: 11, wind: 6, uv: 8, tide: 'Rising', crowd: 'Busy' },
  { id: 'huntington', name: 'Huntington Beach Pier', county: 'Orange', region: 'SoCal', lat: 33.655, lon: -118.001, risk: 'Moderate', p: 0.36, temp: 64, waveFt: 3.5, period: 11, wind: 7, uv: 8, tide: 'Rising', crowd: 'Busy' },
  { id: 'bolsa-chica', name: 'Bolsa Chica', county: 'Orange', region: 'SoCal', lat: 33.685, lon: -118.043, risk: 'Low', p: 0.17, temp: 64, waveFt: 3.1, period: 11, wind: 6, uv: 8, tide: 'Rising', crowd: 'Moderate' },
  { id: 'seal-beach', name: 'Seal Beach', county: 'Orange', region: 'SoCal', lat: 33.738, lon: -118.104, risk: 'High', p: 0.54, temp: 64, waveFt: 2.2, period: 9, wind: 8, uv: 7, tide: 'Low', crowd: 'Moderate' },

  // LA County
  { id: 'long-beach', name: 'Long Beach', county: 'Los Angeles', region: 'SoCal', lat: 33.766, lon: -118.194, risk: 'Very High', p: 0.78, temp: 63, waveFt: 1.4, period: 8, wind: 9, uv: 7, tide: 'Low', crowd: 'Moderate' },
  { id: 'cabrillo', name: 'Cabrillo Beach', county: 'Los Angeles', region: 'SoCal', lat: 33.708, lon: -118.282, risk: 'High', p: 0.61, temp: 63, waveFt: 1.8, period: 9, wind: 8, uv: 7, tide: 'Low', crowd: 'Light' },
  { id: 'redondo', name: 'Redondo Beach', county: 'Los Angeles', region: 'SoCal', lat: 33.842, lon: -118.391, risk: 'Moderate', p: 0.41, temp: 63, waveFt: 2.6, period: 10, wind: 7, uv: 8, tide: 'Rising', crowd: 'Busy' },
  { id: 'hermosa', name: 'Hermosa Beach', county: 'Los Angeles', region: 'SoCal', lat: 33.862, lon: -118.404, risk: 'Low', p: 0.19, temp: 63, waveFt: 2.8, period: 10, wind: 7, uv: 8, tide: 'Rising', crowd: 'Busy' },
  { id: 'manhattan-beach-pier', name: 'Manhattan Beach Pier', county: 'Los Angeles', region: 'SoCal', lat: 33.885, lon: -118.411, risk: 'High', p: 0.64, temp: 63, waveFt: 2.6, period: 10, wind: 8, uv: 7, tide: 'Low', crowd: 'Busy' },
  { id: 'dockweiler', name: 'Dockweiler', county: 'Los Angeles', region: 'SoCal', lat: 33.933, lon: -118.438, risk: 'Moderate', p: 0.39, temp: 63, waveFt: 2.8, period: 10, wind: 8, uv: 8, tide: 'Rising', crowd: 'Moderate' },
  { id: 'venice', name: 'Venice Beach', county: 'Los Angeles', region: 'SoCal', lat: 33.985, lon: -118.473, risk: 'Moderate', p: 0.35, temp: 63, waveFt: 2.6, period: 10, wind: 7, uv: 8, tide: 'Rising', crowd: 'Busy' },
  { id: 'santa-monica', name: 'Santa Monica Pier', county: 'Los Angeles', region: 'SoCal', lat: 34.008, lon: -118.498, risk: 'High', p: 0.56, temp: 63, waveFt: 2.4, period: 10, wind: 8, uv: 7, tide: 'Low', crowd: 'Busy' },
  { id: 'will-rogers', name: 'Will Rogers', county: 'Los Angeles', region: 'SoCal', lat: 34.037, lon: -118.541, risk: 'Moderate', p: 0.32, temp: 62, waveFt: 2.4, period: 10, wind: 7, uv: 8, tide: 'Rising', crowd: 'Moderate' },
  { id: 'malibu', name: 'Malibu Surfrider', county: 'Los Angeles', region: 'SoCal', lat: 34.038, lon: -118.678, risk: 'Low', p: 0.16, temp: 62, waveFt: 3.2, period: 12, wind: 5, uv: 8, tide: 'High', crowd: 'Busy' },
  { id: 'zuma', name: 'Zuma Beach', county: 'Los Angeles', region: 'SoCal', lat: 34.016, lon: -118.823, risk: 'Low', p: 0.11, temp: 62, waveFt: 3.8, period: 12, wind: 6, uv: 8, tide: 'High', crowd: 'Moderate' },
  { id: 'leo-carrillo', name: 'Leo Carrillo', county: 'Los Angeles', region: 'SoCal', lat: 34.046, lon: -118.945, risk: 'Low', p: 0.09, temp: 62, waveFt: 3.4, period: 12, wind: 5, uv: 8, tide: 'High', crowd: 'Light' },

  // Ventura + SB
  { id: 'county-line', name: 'County Line', county: 'Ventura', region: 'SoCal', lat: 34.051, lon: -118.976, risk: 'Low', p: 0.08, temp: 61, waveFt: 3.8, period: 12, wind: 4, uv: 8, tide: 'High', crowd: 'Moderate' },
  { id: 'ventura-point', name: 'Ventura Point', county: 'Ventura', region: 'Central', lat: 34.279, lon: -119.297, risk: 'Moderate', p: 0.28, temp: 60, waveFt: 3.4, period: 12, wind: 6, uv: 7, tide: 'Rising', crowd: 'Moderate' },
  { id: 'rincon', name: 'Rincon Point', county: 'Santa Barbara', region: 'Central', lat: 34.375, lon: -119.478, risk: 'Low', p: 0.07, temp: 60, waveFt: 4.2, period: 13, wind: 3, uv: 7, tide: 'High', crowd: 'Busy' },
  { id: 'carpinteria', name: 'Carpinteria State', county: 'Santa Barbara', region: 'Central', lat: 34.390, lon: -119.516, risk: 'Low', p: 0.13, temp: 60, waveFt: 3.0, period: 11, wind: 5, uv: 7, tide: 'High', crowd: 'Moderate' },
  { id: 'east-beach-sb', name: 'East Beach, SB', county: 'Santa Barbara', region: 'Central', lat: 34.418, lon: -119.679, risk: 'Moderate', p: 0.26, temp: 60, waveFt: 2.4, period: 10, wind: 6, uv: 7, tide: 'Rising', crowd: 'Busy' },
  { id: 'leadbetter', name: 'Leadbetter', county: 'Santa Barbara', region: 'Central', lat: 34.404, lon: -119.696, risk: 'Low', p: 0.14, temp: 60, waveFt: 2.8, period: 11, wind: 5, uv: 7, tide: 'High', crowd: 'Moderate' },
  { id: 'jalama', name: 'Jalama Beach', county: 'Santa Barbara', region: 'Central', lat: 34.513, lon: -120.502, risk: 'Low', p: 0.05, temp: 57, waveFt: 5.2, period: 13, wind: 12, uv: 7, tide: 'Rising', crowd: 'Light' },

  // SLO + Monterey
  { id: 'pismo', name: 'Pismo Beach Pier', county: 'San Luis Obispo', region: 'Central', lat: 35.138, lon: -120.644, risk: 'Low', p: 0.18, temp: 57, waveFt: 3.4, period: 12, wind: 9, uv: 7, tide: 'Rising', crowd: 'Moderate' },
  { id: 'morro-rock', name: 'Morro Rock', county: 'San Luis Obispo', region: 'Central', lat: 35.369, lon: -120.866, risk: 'Low', p: 0.12, temp: 56, waveFt: 4.0, period: 12, wind: 10, uv: 7, tide: 'High', crowd: 'Moderate' },
  { id: 'cayucos', name: 'Cayucos', county: 'San Luis Obispo', region: 'Central', lat: 35.443, lon: -120.900, risk: 'Low', p: 0.15, temp: 56, waveFt: 3.6, period: 12, wind: 10, uv: 7, tide: 'High', crowd: 'Light' },
  { id: 'carmel', name: 'Carmel Beach', county: 'Monterey', region: 'Central', lat: 36.554, lon: -121.928, risk: 'Low', p: 0.09, temp: 55, waveFt: 4.4, period: 13, wind: 8, uv: 6, tide: 'High', crowd: 'Moderate' },
  { id: 'monterey', name: 'Monterey State Beach', county: 'Monterey', region: 'Central', lat: 36.603, lon: -121.892, risk: 'Moderate', p: 0.32, temp: 55, waveFt: 3.0, period: 11, wind: 9, uv: 6, tide: 'Rising', crowd: 'Moderate' },
  { id: 'capitola-beach', name: 'Capitola Beach', county: 'Santa Cruz', region: 'Central', lat: 36.975, lon: -121.953, risk: 'Moderate', p: 0.34, temp: 55, waveFt: 3.2, period: 11, wind: 8, uv: 6, tide: 'Rising', crowd: 'Busy' },
  { id: 'cowells', name: "Cowell's", county: 'Santa Cruz', region: 'Central', lat: 36.957, lon: -122.024, risk: 'Low', p: 0.19, temp: 55, waveFt: 3.6, period: 12, wind: 7, uv: 6, tide: 'High', crowd: 'Busy' },
  { id: 'steamer-lane', name: 'Steamer Lane', county: 'Santa Cruz', region: 'Central', lat: 36.951, lon: -122.027, risk: 'Low', p: 0.12, temp: 55, waveFt: 4.4, period: 13, wind: 6, uv: 6, tide: 'High', crowd: 'Busy' },

  // Bay Area + NorCal
  { id: 'pacifica', name: 'Pacifica State Beach', county: 'San Mateo', region: 'NorCal', lat: 37.596, lon: -122.501, risk: 'Moderate', p: 0.42, temp: 54, waveFt: 4.0, period: 12, wind: 12, uv: 6, tide: 'Rising', crowd: 'Moderate' },
  { id: 'ocean-beach-sf', name: 'Ocean Beach, SF', county: 'San Francisco', region: 'NorCal', lat: 37.759, lon: -122.511, risk: 'Moderate', p: 0.38, temp: 54, waveFt: 5.2, period: 13, wind: 14, uv: 5, tide: 'Rising', crowd: 'Moderate' },
  { id: 'baker', name: 'Baker Beach', county: 'San Francisco', region: 'NorCal', lat: 37.793, lon: -122.484, risk: 'Low', p: 0.21, temp: 54, waveFt: 3.2, period: 11, wind: 13, uv: 5, tide: 'High', crowd: 'Moderate' },
  { id: 'stinson', name: 'Stinson Beach', county: 'Marin', region: 'NorCal', lat: 37.902, lon: -122.646, risk: 'Low', p: 0.18, temp: 54, waveFt: 4.2, period: 12, wind: 11, uv: 5, tide: 'High', crowd: 'Moderate' },
  { id: 'bolinas', name: 'Bolinas', county: 'Marin', region: 'NorCal', lat: 37.907, lon: -122.686, risk: 'Low', p: 0.16, temp: 54, waveFt: 3.6, period: 12, wind: 10, uv: 5, tide: 'High', crowd: 'Light' },
  { id: 'drakes-bay', name: 'Drakes Beach', county: 'Marin', region: 'NorCal', lat: 38.028, lon: -122.960, risk: 'Low', p: 0.08, temp: 53, waveFt: 3.8, period: 12, wind: 12, uv: 5, tide: 'Rising', crowd: 'Light' },
  { id: 'salmon-creek', name: 'Salmon Creek', county: 'Sonoma', region: 'NorCal', lat: 38.366, lon: -123.073, risk: 'Low', p: 0.10, temp: 52, waveFt: 4.6, period: 12, wind: 14, uv: 5, tide: 'Rising', crowd: 'Light' },
  { id: 'mendocino', name: 'Mendocino Headlands', county: 'Mendocino', region: 'NorCal', lat: 39.305, lon: -123.805, risk: 'Low', p: 0.06, temp: 51, waveFt: 5.0, period: 13, wind: 13, uv: 4, tide: 'High', crowd: 'Light' },
  { id: 'trinidad', name: 'Trinidad State Beach', county: 'Humboldt', region: 'NorCal', lat: 41.060, lon: -124.150, risk: 'Low', p: 0.05, temp: 50, waveFt: 5.8, period: 13, wind: 14, uv: 4, tide: 'High', crowd: 'Light' },
];

// Map risk band → color + description
window.RISK_META = {
  'Low':       { tone: 'low',  label: 'Safe to swim', advice: 'Water quality is within safe limits. Have fun out there.', dot: '#22c55e' },
  'Moderate':  { tone: 'mod',  label: 'Caution',      advice: 'Quality is borderline. Avoid if you have open cuts or a weak immune system.', dot: '#f59e0b' },
  'High':      { tone: 'high', label: 'Not ideal',    advice: 'Elevated bacteria risk. Consider a different beach today.', dot: '#f97316' },
  'Very High': { tone: 'vh',   label: 'Avoid',        advice: 'Bacteria exceeds safe thresholds. Swimming not recommended.', dot: '#ef4444' },
};
