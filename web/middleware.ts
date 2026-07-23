import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Belt-and-suspenders: never expose ops/console through the public Next host,
 * even if someone widens rewrites later.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (
    pathname.startsWith("/api/console") ||
    pathname.startsWith("/api/public/ops") ||
    pathname === "/api/console" ||
    pathname === "/api/public/ops"
  ) {
    return NextResponse.json(
      { detail: { code: "not_found", message: "not found" } },
      { status: 404 },
    );
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/api/console/:path*", "/api/public/ops/:path*"],
};
