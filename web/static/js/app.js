/**
 * Email Cleaner — global JS utilities
 * Page-specific logic lives in inline <script> blocks in each template.
 */

// Auto-dismiss flash messages
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.flash').forEach(el => {
    setTimeout(() => el.remove(), 4000);
  });
});
