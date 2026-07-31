import { api } from './client';

export const vendorCategoryMappingApi = {
  taskCategories: () => api('/api/v2/vendor-category-mapping/task-categories'),
  vendorCategories: () => api('/api/v2/vendor-category-mapping/vendor-categories'),
  mappings: () => api('/api/v2/vendor-category-mapping'),
  map: (payload) => api('/api/v2/vendor-category-mapping', {method:'POST', body: JSON.stringify(payload)}),
  unmap: (taskCategoryId) => api(`/api/v2/vendor-category-mapping/${taskCategoryId}`, {method:'DELETE'}),
};
