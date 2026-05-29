import type { CapacitorConfig } from '@capacitor/cli';

// ADR-0006: iPadOS 26 PWA has a confirmed background-audio regression,
// so we ship as a Capacitor app to use UIBackgroundModes=audio.
const config: CapacitorConfig = {
  appId: 'health.vrai.faces',
  appName: 'VRAI Faces',
  webDir: '../core/dist',
  ios: {
    contentInset: 'never',
  },
  server: {
    androidScheme: 'https',
  },
};

export default config;
