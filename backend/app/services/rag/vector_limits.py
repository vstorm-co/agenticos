"""Physical limits shared by provider validation and pgvector index selection."""

# HNSW indexes vector up to 2000 dimensions; wider columns use a halfvec cast.
HNSW_MAX_VECTOR_DIM = 2000
FLOAT32_MAX = 3.4028234663852886e38
HALFVEC_MAX_COMPONENT = 65504.0
