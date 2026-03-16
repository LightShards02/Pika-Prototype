import React from "react";
import { SidebarPanel } from "./panels/SidebarPanel";
import { MapPanel } from "./panels/MapPanel";
import { ImplementPanel } from "./panels/ImplementPanel";
import type { PikaBootstrap, PanelOutgoingMessage, SidebarOutgoingMessage } from "./types";

declare global {
  interface Window {
    __PIKA__: PikaBootstrap;
    acquireVsCodeApi: () => { postMessage: (msg: unknown) => void };
  }
}

interface AppProps {
  postMessage: (message: unknown) => void;
}

/**
 * Root React component.  Reads window.__PIKA__.view to decide which panel to
 * render:  "sidebar" | "map" | "implement"
 */
export function App({ postMessage }: AppProps): React.ReactElement {
  const view = window.__PIKA__?.view ?? "sidebar";

  if (view === "map") {
    return (
      <MapPanel postMessage={(msg: PanelOutgoingMessage) => postMessage(msg)} />
    );
  }

  if (view === "implement") {
    return (
      <ImplementPanel postMessage={(msg: PanelOutgoingMessage) => postMessage(msg)} />
    );
  }

  // Default: sidebar
  return (
    <SidebarPanel postMessage={(msg: SidebarOutgoingMessage) => postMessage(msg)} />
  );
}
