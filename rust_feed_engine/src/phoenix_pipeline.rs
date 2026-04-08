use crate::extra_components::{CacheRequestInfoSideEffect, UserActionSeqQueryHydrator};
use crate::filters::{
    age_filter::AgeFilter,
    previously_seen_posts_filter::PreviouslySeenPostsFilter,
    self_tweet_filter::SelfTweetFilter,
    social_filters::{AuthorSocialgraphFilter, MutedKeywordFilter, RetweetDeduplicationFilter},
    visibility_filter::VisibilityFilter,
};
use crate::hydrators::{
    CoreDataCandidateHydrator, GizmoduckCandidateHydrator, InNetworkCandidateHydrator,
    NeuralContextHydrator, SubscriptionHydrator, VideoDurationCandidateHydrator,
};
use crate::params;
use crate::pipeline::{
    CandidatePipeline, Filter, Hydrator, QueryHydrator, Scorer, Selector, SideEffect, Source,
};
use crate::scorers::{
    diversity_scorer::AuthorDiversityScorer, phoenix_scorer::PhoenixScorer,
    weighted_scorer::WeightedScorer,
};
use crate::selectors::TopKScoreSelector;
use redis::aio::ConnectionManager;
use std::time::Duration;

use crate::sources::{PhoenixSource, ThunderSource};
use qdrant_client::Qdrant;
use std::sync::Arc;

pub struct PhoenixCandidatePipeline {
    query_hydrators: Vec<Box<dyn QueryHydrator>>,
    sources: Vec<Box<dyn Source>>,
    hydrators: Vec<Box<dyn Hydrator>>,
    filters: Vec<Box<dyn Filter>>,
    scorers: Vec<Box<dyn Scorer>>,
    selector: TopKScoreSelector,
    side_effects: Vec<Box<dyn SideEffect>>,
}

impl PhoenixCandidatePipeline {
    pub fn new(redis: ConnectionManager, qdrant: Arc<Qdrant>) -> Self {
        PhoenixCandidatePipeline {
            query_hydrators: vec![Box::new(UserActionSeqQueryHydrator)],
            sources: vec![
                Box::new(PhoenixSource { qdrant }),
                Box::new(ThunderSource {
                    redis: redis.clone(),
                }),
            ],
            hydrators: vec![
                Box::new(InNetworkCandidateHydrator),
                Box::new(CoreDataCandidateHydrator),
                Box::new(VideoDurationCandidateHydrator),
                Box::new(SubscriptionHydrator),
                Box::new(GizmoduckCandidateHydrator),
                Box::new(NeuralContextHydrator {
                    redis: redis.clone(),
                }),
            ],
            filters: vec![
                Box::new(AgeFilter::new(Duration::from_secs(params::MAX_POST_AGE))),
                Box::new(SelfTweetFilter),
                Box::new(PreviouslySeenPostsFilter),
                Box::new(RetweetDeduplicationFilter),
                Box::new(AuthorSocialgraphFilter),
                Box::new(MutedKeywordFilter),
                Box::new(VisibilityFilter),
            ],
            scorers: vec![
                Box::new(PhoenixScorer),
                Box::new(WeightedScorer),
                Box::new(AuthorDiversityScorer),
            ],
            selector: TopKScoreSelector,
            side_effects: vec![Box::new(CacheRequestInfoSideEffect { redis })],
        }
    }
}

impl CandidatePipeline for PhoenixCandidatePipeline {
    fn query_hydrators(&self) -> &[Box<dyn QueryHydrator>] {
        &self.query_hydrators
    }

    fn sources(&self) -> &[Box<dyn Source>] {
        &self.sources
    }

    fn hydrators(&self) -> &[Box<dyn Hydrator>] {
        &self.hydrators
    }

    fn filters(&self) -> &[Box<dyn Filter>] {
        &self.filters
    }

    fn scorers(&self) -> &[Box<dyn Scorer>] {
        &self.scorers
    }

    fn selector(&self) -> &dyn Selector {
        &self.selector
    }

    fn side_effects(&self) -> &[Box<dyn SideEffect>] {
        &self.side_effects
    }
}
