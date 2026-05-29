import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'health.vrai.faces',
  appName: 'VRAI Faces',
  webDir: '../core/dist',
  android: {
    allowMixedContent: false,
  },
};

export default config;
