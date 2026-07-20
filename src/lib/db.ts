import { PrismaClient } from "@prisma/client";

const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

export const prisma = globalForPrisma.prisma ?? new PrismaClient();

// WAL lets reads and writes proceed concurrently instead of locking the whole
// file per commit — without it, every chunked createMany() in the matching/
// price-validation pipeline pays a full fsync, which is what turns a few
// thousand rows into a multi-second stall.
prisma.$executeRawUnsafe("PRAGMA journal_mode = WAL;").catch(() => null);
prisma.$executeRawUnsafe("PRAGMA synchronous = NORMAL;").catch(() => null);

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = prisma;
