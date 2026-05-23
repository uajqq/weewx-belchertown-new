#set $sun_altitude_raw = $almanac.sun.alt
#if $sun_altitude_raw is None
    #set $sun_altitude_raw = -90.0
#end if
#set $sun_rise_raw = $almanac.sun.rise.raw
#set $sun_set_raw = $almanac.sun.set.raw
#set $sun_transit_raw = $almanac.sun.transit.raw
#set $moon_rise_raw = $almanac.moon.rise.raw
#set $moon_set_raw = $almanac.moon.set.raw
#set $moon_transit_raw = $almanac.moon.transit.raw
#if $sun_rise_raw is not None
    #set $sun_rise_az = $almanac($almanac_time=$sun_rise_raw).sun.az
    #set $sun_rise_alt = $almanac($almanac_time=$sun_rise_raw).sun.alt
#else
    #set $sun_rise_az = None
    #set $sun_rise_alt = None
#end if
#if $sun_transit_raw is not None
    #set $sun_transit_az = $almanac($almanac_time=$sun_transit_raw).sun.az
    #set $sun_transit_alt = $almanac($almanac_time=$sun_transit_raw).sun.alt
#else
    #set $sun_transit_az = None
    #set $sun_transit_alt = None
#end if
#if $sun_set_raw is not None
    #set $sun_set_az = $almanac($almanac_time=$sun_set_raw).sun.az
    #set $sun_set_alt = $almanac($almanac_time=$sun_set_raw).sun.alt
#else
    #set $sun_set_az = None
    #set $sun_set_alt = None
#end if
#if $moon_rise_raw is not None
    #set $moon_rise_az = $almanac($almanac_time=$moon_rise_raw).moon.az
    #set $moon_rise_alt = $almanac($almanac_time=$moon_rise_raw).moon.alt
#else
    #set $moon_rise_az = None
    #set $moon_rise_alt = None
#end if
#if $moon_transit_raw is not None
    #set $moon_transit_az = $almanac($almanac_time=$moon_transit_raw).moon.az
    #set $moon_transit_alt = $almanac($almanac_time=$moon_transit_raw).moon.alt
#else
    #set $moon_transit_az = None
    #set $moon_transit_alt = None
#end if
#if $moon_set_raw is not None
    #set $moon_set_az = $almanac($almanac_time=$moon_set_raw).moon.az
    #set $moon_set_alt = $almanac($almanac_time=$moon_set_raw).moon.alt
#else
    #set $moon_set_az = None
    #set $moon_set_alt = None
#end if

#if $sun_rise_az is not None
    #set $sun_rise_az_attr = '%.3f' % $sun_rise_az
#else
    #set $sun_rise_az_attr = ""
#end if
#if $sun_rise_alt is not None
    #set $sun_rise_alt_attr = '%.3f' % $sun_rise_alt
#else
    #set $sun_rise_alt_attr = ""
#end if
#if $sun_transit_az is not None
    #set $sun_transit_az_attr = '%.3f' % $sun_transit_az
#else
    #set $sun_transit_az_attr = ""
#end if
#if $sun_transit_alt is not None
    #set $sun_transit_alt_attr = '%.3f' % $sun_transit_alt
#else
    #set $sun_transit_alt_attr = ""
#end if
#if $sun_set_az is not None
    #set $sun_set_az_attr = '%.3f' % $sun_set_az
#else
    #set $sun_set_az_attr = ""
#end if
#if $sun_set_alt is not None
    #set $sun_set_alt_attr = '%.3f' % $sun_set_alt
#else
    #set $sun_set_alt_attr = ""
#end if
#if $moon_rise_az is not None
    #set $moon_rise_az_attr = '%.3f' % $moon_rise_az
#else
    #set $moon_rise_az_attr = ""
#end if
#if $moon_rise_alt is not None
    #set $moon_rise_alt_attr = '%.3f' % $moon_rise_alt
#else
    #set $moon_rise_alt_attr = ""
#end if
#if $moon_transit_az is not None
    #set $moon_transit_az_attr = '%.3f' % $moon_transit_az
#else
    #set $moon_transit_az_attr = ""
#end if
#if $moon_transit_alt is not None
    #set $moon_transit_alt_attr = '%.3f' % $moon_transit_alt
#else
    #set $moon_transit_alt_attr = ""
#end if
#if $moon_set_az is not None
    #set $moon_set_az_attr = '%.3f' % $moon_set_az
#else
    #set $moon_set_az_attr = ""
#end if
#if $moon_set_alt is not None
    #set $moon_set_alt_attr = '%.3f' % $moon_set_alt
#else
    #set $moon_set_alt_attr = ""
#end if
