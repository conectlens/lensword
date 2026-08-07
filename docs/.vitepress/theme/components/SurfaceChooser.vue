<script setup lang="ts">
import registry from '../../../internal/product-registry.json'

// Reuses the canonical product/use-case registry built for issue #269
// instead of re-describing each surface's status in Markdown by hand —
// this table and docs/internal/repo-audit.md derive from the same data.
const STATUS_CLASS: Record<string, string> = {
  public: 'lw-status-public',
  'public-dev-mode-only': 'lw-status-partial',
  'public-source-install-only': 'lw-status-partial',
  unreleased: 'lw-status-unreleased',
  'internal-shared-dependency': 'lw-status-partial',
}

const rows = registry.products
  .filter((p: any) => p.kind === 'public-product')
  .map((p: any) => ({
    id: p.id,
    name: p.name,
    purpose: p.purpose,
    install: Array.isArray(p.install) ? p.install[0] : p.install,
    requires: Array.isArray(p.runtimeDependencies) ? p.runtimeDependencies.join(', ') : '—',
    status: p.status,
    statusClass: STATUS_CLASS[p.status] || 'lw-status-partial',
    statusNote: p.statusNote,
  }))
</script>

<template>
  <table class="lw-surface-table">
    <thead>
      <tr>
        <th>Surface</th>
        <th>Purpose</th>
        <th>Requires</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="row in rows" :key="row.id">
        <td><strong>{{ row.name }}</strong></td>
        <td>{{ row.purpose }}</td>
        <td>{{ row.requires }}</td>
        <td>
          <span class="lw-status" :class="row.statusClass">{{ row.status }}</span>
          <div v-if="row.statusNote" class="lw-status-note">{{ row.statusNote }}</div>
        </td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.lw-surface-table {
  width: 100%;
  display: table;
}
.lw-status-note {
  margin-top: 0.25em;
  font-size: 0.85em;
  color: var(--vp-c-text-2);
}
</style>
