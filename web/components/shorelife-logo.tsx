import Image from "next/image";

interface ShoreLifeLogoProps {
  size?: number;
  className?: string;
}

export function ShoreLifeLogo({ size = 48, className = "" }: ShoreLifeLogoProps) {
  return (
    <Image
      src="/images/shorelife-logo.png"
      alt="ShoreLife Logo - Ocean waves forming an S shape on a beach coastline"
      width={size}
      height={size}
      className={`rounded-lg ${className}`}
      priority
    />
  );
}
