use crate::models::{PostCandidate, ScoredPostsQuery};
use async_trait::async_trait;

pub struct FilterResult<T> {
    pub kept: Vec<T>,
    pub removed: Vec<T>,
}

#[async_trait]
pub trait Source: Send + Sync {
    async fn get_candidates(&self, query: &ScoredPostsQuery) -> Result<Vec<PostCandidate>, String>;
}

#[async_trait]
pub trait Hydrator: Send + Sync {
    async fn hydrate(&self, query: &ScoredPostsQuery, candidates: Vec<PostCandidate>) -> Result<Vec<PostCandidate>, String>;
}

#[async_trait]
pub trait Filter: Send + Sync {
    async fn filter(&self, query: &ScoredPostsQuery, candidates: Vec<PostCandidate>) -> Result<FilterResult<PostCandidate>, String>;
}

#[async_trait]
pub trait Scorer: Send + Sync {
    async fn score(&self, query: &ScoredPostsQuery, candidates: Vec<PostCandidate>) -> Result<Vec<PostCandidate>, String>;
}

pub trait Selector: Send + Sync {
    fn select(&self, query: &ScoredPostsQuery, candidates: Vec<PostCandidate>) -> Vec<PostCandidate>;
}

#[async_trait]

pub trait QueryHydrator: Send + Sync {

    async fn hydrate(&self, query: &mut ScoredPostsQuery) -> Result<(), String>;

}



#[async_trait]

pub trait SideEffect: Send + Sync {

    async fn execute(&self, query: &ScoredPostsQuery, candidates: &[PostCandidate]);

}



#[async_trait]

pub trait CandidatePipeline: Send + Sync {

    fn query_hydrators(&self) -> &[Box<dyn QueryHydrator>];

    fn sources(&self) -> &[Box<dyn Source>];

    fn hydrators(&self) -> &[Box<dyn Hydrator>];

    fn filters(&self) -> &[Box<dyn Filter>];

    fn scorers(&self) -> &[Box<dyn Scorer>];

    fn selector(&self) -> &dyn Selector;

    fn side_effects(&self) -> &[Box<dyn SideEffect>];

    

    async fn execute(&self, mut query: ScoredPostsQuery) -> Result<Vec<PostCandidate>, String> {

        // 0. Hydrate Query

        for qh in self.query_hydrators() {

            qh.hydrate(&mut query).await?;

        }



        // 1. Fetch from Sources

        let mut candidates = Vec::new();

        for source in self.sources() {

            let fetched = source.get_candidates(&query).await?;

            candidates.extend(fetched);

        }

        

        // 2. Hydrate Candidates

        for hydrator in self.hydrators() {

            candidates = hydrator.hydrate(&query, candidates).await?;

        }

        

                // 3. Filter

        

                if !query.in_network_only {

        

                    for filter in self.filters() {

        

                        let result = filter.filter(&query, candidates).await?;

        

                        candidates = result.kept;

        

                    }

        

                }

        

        

        

        // 4. Score

        for scorer in self.scorers() {

            candidates = scorer.score(&query, candidates).await?;

        }

        

        // 5. Select

        candidates = self.selector().select(&query, candidates);



        // 6. Side Effects (Fire and forget or wait)

        for se in self.side_effects() {

            se.execute(&query, &candidates).await;

        }

        

        Ok(candidates)

    }

}
