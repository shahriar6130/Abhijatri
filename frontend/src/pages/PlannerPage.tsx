import React from 'react';
import { Calculator } from 'lucide-react';
import { FeatureUnavailable } from '../components/common/FeatureUnavailable';

/** Cost planner (E08). The estimate API (E07) does not exist yet, so nothing is calculated here. */
export const PlannerPage: React.FC = () => (
  <FeatureUnavailable
    icon={Calculator}
    title={['ভ্রমণ খরচ পরিকল্পনা', 'Trip cost planner']}
    summary={[
      'খরচের হিসাব সূত্র ও তারিখসহ যাচাইকৃত দামের তালিকা থেকে আসবে। সেই তালিকা ও হিসাবের সেবা তৈরি না হওয়া পর্যন্ত এখানে কোনো অনুমানিক সংখ্যা দেখানো হবে না।',
      'Estimates will come from a source-dated, verified price catalogue. Until that catalogue and the estimate service exist, no guessed figures are shown here.',
    ]}
    plannedPoints={[
      ['যাত্রী সংখ্যা, দিন-রাত ও খরচের ধরন অনুযায়ী টাকায় খরচ', 'Costs in BDT by party size, days and nights, and comfort tier'],
      ['ভাগ করা ও জনপ্রতি খরচ আলাদা করে দেখানো', 'Shared and per-person costs shown separately'],
      ['প্রতিটি দামের সূত্র, তারিখ ও নির্ভরযোগ্যতা', 'Source, date and confidence for every price'],
      ['হিসাব ভ্রমণ সংক্ষেপ হিসেবে সংরক্ষণ', 'Save an estimate as a trip brief'],
    ]}
    task="E06–E08"
    alternatives={[
      { to: '/destinations', label: ['গন্তব্য গাইড দেখুন', 'Browse destination guides'] },
    ]}
  />
);
