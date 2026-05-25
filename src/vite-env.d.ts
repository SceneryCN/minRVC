/// <reference types="vite/client" />

declare module '*.module.css' {
  const classes: Readonly<Record<string, string>>;
  export default classes;
}

declare module '*.css';

declare module '*.svg' {
  const src: string;
  export default src;
}
