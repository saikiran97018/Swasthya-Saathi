/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional absolute backend origin, e.g. https://api.example.com (default: same origin via the dev proxy). */
  readonly VITE_API_BASE?: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
