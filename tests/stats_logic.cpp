#include "../src/stats_logic.h"
#include <cassert>
#include <iostream>
#include <string>
int main(){
    // No rate until a minute of readings; then tenths of a percent per hour.
    XpTracker t;assert(t.perHour()==-1&&t.minutesToLevel()==-1);
    t.add(200,0);t.add(250,30000);assert(t.perHour()==-1);
    t.add(300,60000);assert(t.perHour()==6000);              // +10% in a minute = 600%/h
    assert(t.minutesToLevel()==7);                            // 70% left at 600%/h
    // A level-up wraps the bar: 95% -> 3% is +8%, and counts a level.
    XpTracker w;w.add(950,0);w.add(30,60000);assert(w.levels==1&&w.gained==80&&w.perHour()==4800);
    // A small drop (death, misread) adds nothing and isn't a level.
    XpTracker d;d.add(500,0);d.add(450,30000);d.add(470,60000);assert(d.levels==0&&d.gained==20);
    // Out-of-range readings are ignored.
    XpTracker o;o.add(-1,0);o.add(1001,0);assert(o.lastXp==-1);
    // Clock wraparound keeps the elapsed time right.
    XpTracker c;c.add(100,0xFFFF0000u);c.add(200,0xFFFF0000u+120000u);assert(c.perHour()==3000);
    // Live potions: threshold in whole percent, readings in tenths.
    assert(liveDecides(50,true)&&!liveDecides(0,true)&&!liveDecides(50,false));
    assert(liveWantsPotion(50,499,false,0)&&!liveWantsPotion(50,500,false,0)&&!liveWantsPotion(50,-1,false,0));
    assert(!liveWantsPotion(50,100,true,LIVE_POTION_GAP_MS-1)&&liveWantsPotion(50,100,true,LIVE_POTION_GAP_MS));
    // Game state: anything but OK names a stop reason.
    assert(!liveStopReason(LIVE_OK)&&std::string(liveStopReason(LIVE_DEAD))=="you died"&&liveStopReason(LIVE_OFFLINE)&&liveStopReason(LIVE_MAP_CHANGED));
    // Facing: map edges first, then mobs on one side only; stale data has no opinion.
    assert(liveFacing(true,50,120,true,MOB_LEFT)==1);      // near the left edge: face right, even with a mob left
    assert(liveFacing(true,950,120,true,MOB_RIGHT)==-1);   // near the right edge
    assert(liveFacing(true,500,120,true,MOB_LEFT)==-1&&liveFacing(true,500,120,true,MOB_RIGHT)==1);
    assert(liveFacing(true,500,120,true,MOB_LEFT|MOB_RIGHT)==0&&liveFacing(true,500,120,true,0)==0);
    assert(liveFacing(true,500,120,false,MOB_LEFT)==0&&liveFacing(true,50,0,true,0)==0);   // features off
    assert(liveFacing(true,-1,120,true,0)==0&&liveFacing(false,50,120,true,MOB_LEFT)==0);   // no position / stale
    // Stuck: still for the window -> 1 (turn), still again -> 2 (stop); moving resets.
    StuckWatch sw;assert(sw.update(true,500,500,0,10000)==0&&sw.update(true,505,498,9999,10000)==0);
    assert(sw.update(true,505,498,10000,10000)==1&&sw.update(true,500,500,15000,10000)==0&&sw.update(true,500,500,20000,10000)==2);
    assert(sw.update(true,600,500,21000,10000)==0&&sw.strikes==0);   // moved away: fine again
    assert(sw.update(false,0,0,40000,10000)==0&&!sw.has);           // position lost: start over
    StuckWatch far;assert(far.update(true,-2400,1300,0,10000)==0&&far.update(true,-2395,1300,10000,10000)==1);   // map positions past the minimap's edges work too
    // Readings: Wi-Fi and USB share one parser; blanks and junk are "not read".
    assert(statsTenths("72.5")==725&&statsTenths("0")==0&&statsTenths("100")==1000);
    assert(statsTenths("")==-1&&statsTenths(nullptr)==-1&&statsTenths("abc")==-1&&statsTenths("7x")==-1&&statsTenths("101")==-1&&statsTenths("-1")==-1&&statsTenths("nan")==-1);
    assert(statsState("dead")==LIVE_DEAD&&statsState("offline")==LIVE_OFFLINE&&statsState("map")==LIVE_MAP_CHANGED&&statsState("ok")==LIVE_OK&&statsState("??")==LIVE_OK);
    assert(statsMobs("LR")==(MOB_LEFT|MOB_RIGHT)&&statsMobs("R")==MOB_RIGHT&&statsMobs("")==0);
    assert(statsPos("1415")==1415&&statsPos("-250")==-250&&statsPos("0")==0&&statsPos("100000")==100000);
    assert(statsPos("")==LIVE_NO_POS&&statsPos(nullptr)==LIVE_NO_POS&&statsPos("12.5")==LIVE_NO_POS&&statsPos("x")==LIVE_NO_POS&&statsPos("100001")==LIVE_NO_POS);
    StatsReading r=parseStatsForm("hp=72.0&xp=63.2&x=41.5&y=70.0&wx=-1585&wy=740&state=dead&mobs=L");
    assert(r.hp==720&&r.mana==-1&&r.xp==632&&r.x==415&&r.y==700&&r.wx==-1585&&r.wy==740&&r.state==LIVE_DEAD&&r.mobs==MOB_LEFT);
    r=parseStatsForm("hp=&mana=40.0&state=ok&mobs=&junk=1&averyveryverylongkey=5&hp2=9");
    assert(r.hp==-1&&r.mana==400&&r.state==LIVE_OK&&r.mobs==0&&r.x==-1&&r.wx==LIVE_NO_POS);
    r=parseStatsForm("");assert(r.hp==-1&&r.state==LIVE_OK);
    r=parseStatsForm("hp=12345678901234567890&mana");assert(r.hp==-1&&r.mana==-1);   // oversized value, no '='
    std::cout<<"stats logic tests passed\n";
}
