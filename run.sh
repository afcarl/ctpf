#!/bin/bash
# this script is for debugging and quick runs
dir=/home/statler/lcharlin/arxiv/dat/dataset_toy/
out_dir=/home/waldorf/altosaar/projects/arxiv/fit/2015-11-9-debug/

# dir=/home/statler/lcharlin/arxiv/dat/dataset_2003-2012_clean/
# out_dir=/home/waldorf/altosaar/projects/arxiv/fit/hpmf-categorywise/
# out_dir=/home/waldorf/altosaar/projects/arxiv/fit/ctpf-stagewise-heldout/

python job_handler.py \
  --train_file=${dir}train.tsv \
  --validation_file=${dir}validation.tsv \
  --test_file=${dir}test.tsv \
  --item_info_file=${dir}items_arxiv_info.tsv \
  --user_info_file=${dir}users.tsv \
  --out_dir=${out_dir} \
  --binarize_true \
  --model=pmf \
  --item_fit_type=converge_in_category_first \
  --user_fit_type=converge_separately \
  --min_iterations=3 \
  --zero_untrained_components_false \
  --observed_topics_true \
  --categorywise_true \
  --trained_user_preferences_file=/home/waldorf/altosaar/projects/arxiv/fit/fit.h5 \
  --stdout \
