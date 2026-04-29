import React from "react";

export function EditorialPage({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ maxWidth: 1280, margin: "0 auto" }}>
      {children}
    </div>
  );
}
