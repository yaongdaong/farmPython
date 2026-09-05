// @ts-nocheck
import { defineConfig } from 'prisma/config';

export default defineConfig({
  schema: 'prisma/schema.prisma',
  datasource: {
    // env() 함수 대신 JS 전용 process.env를 사용하고, 값이 없을 경우 'file:./dev.db'로 우회합니다.
    url: process.env.DATABASE_URL ?? 'file:./dev.db',
  },
});