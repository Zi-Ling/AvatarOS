import React from "react";
import Image from "next/image";

export function Branding() {
  return (
    <div className="flex items-center justify-center py-4">
      <div className="relative w-10 h-10 rounded-xl overflow-hidden shadow-lg shadow-indigo-500/20 group cursor-pointer transition-transform hover:scale-105 active:scale-95">
         <Image src="/logo.png" alt="Logo" fill className="object-cover" />
      </div>
    </div>
  );
}

