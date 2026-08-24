This file is to store the contract how the backend should communicate with the database. For now, I am thinking the backend should send the request similar to the one below:
{
    start_date: ...
    end_date: ...
    topic_taxomony: bitflags (calculated from schema.py)
    event_type: [
        event_type1,
        event_type2,
        ...
    ]
    categories: [
        category1,
        category2,
        ...
    ]
    categories_audience: [
        categories_audience1,
        categories_audience2,
        ...
    ]
}

Within each category, use OR to connect each one (e.g., for event_type, search for event_type1 OR event_type2 OR ...). Among those categories, use AND to connect them (topic_taxomony bitflags AND (event_type1 OR event_type2 OR ...) AND ...)